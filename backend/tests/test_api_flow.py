"""Fluxo individual completo pela API: cadastro → gerador → upload → campos → gerar → baixar."""

from __future__ import annotations

from tests.flows import SAMPLE_VALUES, build_generator, docx_text, upload


def test_register_login_logout_and_me(api):
    reg = api.register("ana@exemplo.test")
    assert reg["workspace"]["role"] == "owner" and reg["csrf_token"]
    me = api.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "ana@exemplo.test"
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/auth/me").status_code == 401
    r = api.post("/auth/login", json={"email": "ana@exemplo.test", "password": "senha-forte-123"})
    assert r.status_code == 200
    assert (
        api.post("/auth/login", json={"email": "ana@exemplo.test", "password": "errada"}).status_code == 401
    )


def test_cookies_are_httponly_and_csrf_is_enforced(api):
    r = api.tc.post(
        "/api/v1/auth/register",
        json={"name": "Bia", "email": "bia@exemplo.test", "password": "senha-forte-123"},
    )
    set_cookie = r.headers.get_list("set-cookie")
    assert any("minuta_session" in c and "HttpOnly" in c and "SameSite=lax" in c for c in set_cookie)
    assert any("minuta_csrf" in c and "HttpOnly" not in c for c in set_cookie)
    # método inseguro sem o cabeçalho CSRF é recusado, mesmo com cookie de sessão
    bad = api.tc.post("/api/v1/generators", json={"name": "X"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "FORBIDDEN"
    ok = api.post("/generators", json={"name": "X"})
    assert ok.status_code == 201


def test_password_policy_and_duplicate_email(api):
    r = api.post("/auth/register", json={"name": "Ana", "email": "a@x.test", "password": "123"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "WEAK_PASSWORD"
    api.register("dup@exemplo.test")
    r = api.post(
        "/auth/register", json={"name": "Outra", "email": "dup@exemplo.test", "password": "senha-forte-123"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_full_individual_flow(api, demo_docx):
    api.register()
    built = build_generator(api, demo_docx)
    gid = built["id"]
    occ = built["occurrences"]
    assert occ[built["fields"]["nome"]["id"]] == 5  # campo reutilizado 5 vezes
    assert occ[built["fields"]["valor"]["id"]] == 2

    gen = api.get(f"/generators/{gid}").json()
    assert gen["status"] == "active" and gen["fields_count"] == 7 and gen["has_template"] is True

    # formulário + prévia
    form = api.get(f"/generators/{gid}/form").json()
    assert next(f["name"] for f in form["fields"]) == "nome_do_contratante" and form["pdf_available"] is False

    # gerar DOCX
    r = api.post(
        f"/generators/{gid}/generate",
        json={"values": SAMPLE_VALUES, "format": "docx"},
        headers={"Idempotency-Key": "k-1"},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "succeeded" and job["succeeded_items"] == 1 and job["kind"] == "single"
    (file,) = job["files"]
    link = api.post(f"/files/{file['id']}/link").json()
    dl = api.tc.get(link["url"])
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("application/vnd.openxmlformats")
    text = docx_text(dl.content)
    assert "Maria Souza" in text and "João da Silva" not in text
    assert "R$ 1.234,50" in text and "R$ 5.000,00" not in text
    assert "529.982.247-25" in text and "15/11/2026" in text and "Suporte técnico mensal" in text
    assert "Renovação automática: Não." in text


def test_validation_errors_come_from_server(api, demo_docx):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    bad = dict(SAMPLE_VALUES, cpf_do_contratante="111.111.111-11", valor_mensal="abc", nome_do_contratante="")
    r = api.post(f"/generators/{gid}/generate", json={"values": bad})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "BATCH_INVALID_ROWS"
    errors = err["details"]["invalid_rows"][0]["errors"]
    assert (
        errors["CPF do contratante"] == "CPF inválido."
        and errors["Nome do contratante"] == "Campo obrigatório."
    )


def test_pdf_requires_converter_and_reports_clearly(api, demo_docx):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    r = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "pdf"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "PDF_CONVERTER_UNAVAILABLE"


def test_pdf_pipeline_with_converter_double(api, demo_docx, fake_pdf):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    job = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "both"}).json()
    assert job["status"] == "succeeded"
    assert sorted(f["kind"] for f in job["files"]) == ["docx", "pdf"]
    pdf = next(f for f in job["files"] if f["kind"] == "pdf")
    body = api.tc.get(api.post(f"/files/{pdf['id']}/link").json()["url"]).content
    assert body.startswith(b"%PDF-")


def test_upload_rejects_bad_files(api, demo_docx):
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    assert upload(api, gid, b"nao sou um docx").json()["error"]["code"] == "NOT_A_DOCX"
    assert upload(api, gid, demo_docx, "contrato.pdf").json()["error"]["code"] == "NOT_A_PDF"
    assert upload(api, gid, demo_docx, "contrato.odt").json()["error"]["code"] == "INVALID_EXTENSION"
    assert upload(api, gid, b"", "vazio.docx").json()["error"]["code"] == "EMPTY_FILE"


def test_generation_requires_fields(api, demo_docx):
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    upload(api, gid, demo_docx)
    r = api.post(f"/generators/{gid}/generate", json={"values": {}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_FIELDS"


def test_duplicate_field_names_and_options_are_rejected(api, demo_docx):
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    upload(api, gid, demo_docx)
    assert (
        api.post(f"/generators/{gid}/fields", json={"label": "Nome", "type": "text_short"}).status_code == 201
    )
    dup = api.post(f"/generators/{gid}/fields", json={"label": "Outro", "name": "nome", "type": "text_short"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_FIELD_NAME"
    same_label = api.post(f"/generators/{gid}/fields", json={"label": "Nome", "type": "text_short"}).json()
    assert same_label["name"] == "nome_2"  # nome técnico gerado é único
    sel = api.post(
        f"/generators/{gid}/fields", json={"label": "Serviço", "type": "select", "options": [{"label": "A"}]}
    ).json()
    dupopt = api.put(f"/fields/{sel['id']}/options", json={"options": [{"label": "A"}, {"label": "a"}]})
    assert dupopt.status_code == 422 and dupopt.json()["error"]["code"] == "DUPLICATE_OPTION"
    ok = api.put(
        f"/fields/{sel['id']}/options",
        json={"options": [{"label": "Um", "value": "1"}, {"label": "Dois", "value": "2"}]},
    )
    assert [o["value"] for o in ok.json()["options"]] == ["1", "2"]


def test_delete_field_keep_or_remove_text(api, demo_docx):
    api.register()
    built = build_generator(api, demo_docx)
    gid, valor = built["id"], built["fields"]["valor"]
    r = api.delete(f"/fields/{valor['id']}?occurrences=keep_text")
    assert r.status_code == 200 and r.json()["affected_occurrences"] == 2
    ed = api.get(f"/generators/{gid}/editor").json()
    assert "R$ 5.000,00" in str(ed["doc"])  # texto original voltou ao documento
    assert all(f["id"] != valor["id"] for f in ed["fields"])


def test_currency_in_words_goes_to_the_document(api, demo_docx):
    """Contratos repetem o valor por extenso: config currency_format="words" → "R$ 1.234,50 (mil … centavos)"."""
    api.register()
    built = build_generator(api, demo_docx)
    gid, valor = built["id"], built["fields"]["valor"]
    bad = api.patch(f"/fields/{valor['id']}", json={"config": {"currency_format": "romano"}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_CONFIG"
    ok = api.patch(f"/fields/{valor['id']}", json={"config": {"currency_format": "words"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["config"]["currency_format"] == "words"

    job = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "docx"}).json()
    (file,) = job["files"]
    dl = api.tc.get(api.post(f"/files/{file['id']}/link").json()["url"])
    text = docx_text(dl.content)
    assert "R$ 1.234,50 (mil duzentos e trinta e quatro reais e cinquenta centavos)" in text

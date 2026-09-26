"""Kit de documentos: membros, campos compartilhados (auto-detect e mapeamento manual), geração e ZIP."""

from __future__ import annotations

import csv
import io
import zipfile

from app.adapters.ai.typesafe import RoleClassifierUnavailable
from app.modules.kits.matching import RoleAnswer
from tests.flows import SAMPLE_VALUES, build_generator


def _two_generators(api, demo_docx) -> tuple[str, str]:
    a = build_generator(api, demo_docx, name="Contrato A")["id"]
    b = build_generator(api, demo_docx, name="Contrato B")["id"]
    return a, b


def _new_kit(api, name: str = "Kit de admissão") -> str:
    r = api.post("/kits", json={"name": name, "description": "Documentos do processo"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_kit_crud_pin_and_archive(api):
    api.register()
    kid = _new_kit(api)
    got = api.get(f"/kits/{kid}").json()
    assert got["name"] == "Kit de admissão" and got["status"] == "active" and got["is_pinned"] is False
    assert got["items_count"] == 0 and got["fields_count"] == 0

    patched = api.patch(f"/kits/{kid}", json={"name": "Kit renomeado", "filename_pattern": "Kit_{hoje}"})
    assert patched.status_code == 200 and patched.json()["name"] == "Kit renomeado"

    assert api.post(f"/kits/{kid}/pin").json()["is_pinned"] is True
    assert api.post(f"/kits/{kid}/unpin").json()["is_pinned"] is False

    assert api.post(f"/kits/{kid}/archive").json()["status"] == "archived"
    assert api.get("/kits").json()["total"] == 0  # arquivado some da listagem padrão
    assert api.get("/kits?status=archived").json()["total"] == 1
    assert api.post(f"/kits/{kid}/unarchive").json()["status"] == "active"

    assert api.delete(f"/kits/{kid}").status_code == 204
    assert api.get(f"/kits/{kid}").status_code == 404
    assert api.get("/kits").json()["total"] == 0


def test_add_items_rejects_generator_without_template_and_duplicates(api, demo_docx):
    api.register()
    empty_gid = api.post("/generators", json={"name": "Sem modelo"}).json()["id"]
    kid = _new_kit(api)
    bad = api.post(f"/kits/{kid}/items", json={"generator_id": empty_gid})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "GENERATOR_WITHOUT_TEMPLATE"

    gid, _ = _two_generators(api, demo_docx)
    ok = api.post(f"/kits/{kid}/items", json={"generator_id": gid})
    assert ok.status_code == 201 and ok.json()["generator_id"] == gid and ok.json()["usable"] is True
    dup = api.post(f"/kits/{kid}/items", json={"generator_id": gid})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "ALREADY_IN_KIT"


def test_auto_detect_groups_shared_fields_and_leaves_per_document_fields(api, demo_docx):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})

    r = api.post(f"/kits/{kid}/auto-detect")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_fields"] == 5  # nome, cpf, cnpj, valor, data (select/yes_no ficam de fora)

    fields = api.get(f"/kits/{kid}/fields").json()["items"]
    labels = {f["label"] for f in fields}
    assert labels == {
        "Nome do contratante",
        "CPF do contratante",
        "CNPJ da contratada",
        "Valor mensal",
        "Data de início",
    }
    types = {f["label"]: f["type"] for f in fields}
    assert types["CPF do contratante"] == "cpf" and types["Valor mensal"] == "currency"

    items = api.get(f"/kits/{kid}/items").json()["items"]
    for it in items:
        assert len(it["field_mapping"]) == 5
        # tipo de serviço (select) e renovação automática (yes_no) continuam só daquele documento
        extra_labels = {f["label"] for f in it["fields"] if f["name"] in it["extra_field_names"]}
        assert extra_labels == {"Tipo de serviço", "Renovação automática"}

    # rodar de novo não duplica os campos (atualiza o mapeamento em vez de criar outro)
    again = api.post(f"/kits/{kid}/auto-detect").json()
    assert again["created_fields"] == 0 and again["updated_fields"] == 5
    assert len(api.get(f"/kits/{kid}/fields").json()["items"]) == 5


def test_manual_mapping_requires_matching_type(api, demo_docx):
    api.register()
    gid, _ = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    item = api.post(f"/kits/{kid}/items", json={"generator_id": gid}).json()
    kf = api.post(f"/kits/{kid}/fields", json={"label": "Documento", "type": "text_short"}).json()

    ok = api.put(
        f"/kits/{kid}/items/{item['id']}/mapping", json={"mapping": {kf["name"]: "nome_do_contratante"}}
    )
    assert ok.status_code == 200 and ok.json()["field_mapping"][kf["name"]] == "nome_do_contratante"

    bad = api.put(
        f"/kits/{kid}/items/{item['id']}/mapping", json={"mapping": {kf["name"]: "cpf_do_contratante"}}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "TYPE_MISMATCH"

    unknown = api.put(f"/kits/{kid}/items/{item['id']}/mapping", json={"mapping": {"nao_existe": "x"}})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_KIT_FIELD"


def _kit_values() -> dict[str, str]:
    return {
        "nome_do_contratante": SAMPLE_VALUES["nome_do_contratante"],
        "cpf_do_contratante": SAMPLE_VALUES["cpf_do_contratante"],
        "cnpj_da_contratada": SAMPLE_VALUES["cnpj_da_contratada"],
        "valor_mensal": SAMPLE_VALUES["valor_mensal"],
        "data_de_inicio": SAMPLE_VALUES["data_de_inicio"],
    }


def _member_extra(gid: str) -> dict[str, str]:
    return {
        "tipo_de_servico": SAMPLE_VALUES["tipo_de_servico"],
        "renovacao_automatica": SAMPLE_VALUES["renovacao_automatica"],
    }


def test_kit_run_generates_all_members_and_bundles_zip_with_report(api, demo_docx):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")

    form = api.get(f"/kits/{kid}/form").json()
    assert len(form["members"]) == 2 and form["warnings"] == []

    body = {
        "values": _kit_values(),
        "member_values": {gid_a: _member_extra(gid_a), gid_b: _member_extra(gid_b)},
        "format": "docx",
    }
    r = api.post(f"/kits/{kid}/runs", json=body, headers={"Idempotency-Key": "kit-run-1"})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "succeeded" and run["total_members"] == 2 and run["succeeded_items"] == 2
    assert len(run["members"]) == 2
    for m in run["members"]:
        assert m["job"]["status"] == "succeeded" and m["job"]["kit_run_id"] == run["id"]

    # o zip + relatório já vêm prontos (bundle construído na leitura, uma vez que os jobs terminaram)
    kinds = {f["kind"] for f in run["files"]}
    assert kinds == {"zip", "report"}
    zip_file = next(f for f in run["files"] if f["kind"] == "zip")
    url = api.post(f"/files/{zip_file['id']}/link").json()["url"]
    z = zipfile.ZipFile(io.BytesIO(api.tc.get(url).content))
    names = z.namelist()
    assert len([n for n in names if n.endswith(".docx")]) == 2 and "relatorio.csv" in names
    report = z.read("relatorio.csv").decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(report), delimiter=";"))
    assert rows[0] == ["documento", "status", "arquivos", "codigo_erro", "mensagem"]
    assert [r[1] for r in rows[1:]] == ["gerado", "gerado"]

    # cada geração do kit também aparece no histórico comum, marcada com o kit_run_id
    jobs = api.get("/jobs").json()["items"]
    kit_jobs = [j for j in jobs if j.get("kit_run_id") == run["id"]]
    assert len(kit_jobs) == 2

    # repetir com a mesma chave de idempotência devolve o mesmo run, sem duplicar jobs
    again = api.post(f"/kits/{kid}/runs", json=body, headers={"Idempotency-Key": "kit-run-1"})
    assert again.status_code == 200 and again.json()["id"] == run["id"]
    assert len(api.get(f"/jobs?generator_id={gid_a}").json()["items"]) == 1


def test_kit_run_with_pdf_format(api, demo_docx, fake_pdf):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")
    body = {
        "values": _kit_values(),
        "member_values": {gid_a: _member_extra(gid_a), gid_b: _member_extra(gid_b)},
        "format": "both",
    }
    run = api.post(f"/kits/{kid}/runs", json=body).json()
    assert run["status"] == "succeeded"
    for m in run["members"]:
        assert sorted(f["kind"] for f in m["job"]["files"]) == ["docx", "pdf"]


def test_kit_run_rejects_invalid_values_for_any_member(api, demo_docx):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")

    values = _kit_values()
    values["cpf_do_contratante"] = "111.111.111-11"  # inválido
    body = {"values": values, "member_values": {gid_a: _member_extra(gid_a), gid_b: _member_extra(gid_b)}}
    r = api.post(f"/kits/{kid}/runs", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "KIT_INVALID_VALUES"
    problems = r.json()["error"]["details"]["problems"]
    assert len(problems) == 2  # o CPF inválido afeta os dois documentos
    assert api.get("/jobs").json()["total"] == 0  # nada foi criado


def test_kit_form_flags_member_whose_generator_was_deleted(api, demo_docx):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")

    assert api.delete(f"/generators/{gid_b}").status_code == 204
    form = api.get(f"/kits/{kid}/form").json()
    assert len(form["warnings"]) == 1
    by_gen = {m["generator_id"]: m for m in form["members"]}
    assert by_gen[gid_b]["usable"] is False and by_gen[gid_a]["usable"] is True

    # gerar o kit segue funcionando só com o documento que restou
    body = {"values": _kit_values(), "member_values": {gid_a: _member_extra(gid_a)}}
    run = api.post(f"/kits/{kid}/runs", json=body).json()
    assert run["total_members"] == 1 and run["status"] == "succeeded"


def test_remove_item_and_delete_kit_field_clears_mapping(api, demo_docx):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    item_a = api.post(f"/kits/{kid}/items", json={"generator_id": gid_a}).json()
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")

    assert api.delete(f"/kits/{kid}/items/{item_a['id']}").status_code == 204
    assert len(api.get(f"/kits/{kid}/items").json()["items"]) == 1

    kf = api.get(f"/kits/{kid}/fields").json()["items"][0]
    assert api.delete(f"/kit-fields/{kf['id']}").status_code == 204
    remaining = api.get(f"/kits/{kid}/fields").json()["items"]
    assert kf["id"] not in {f["id"] for f in remaining}
    for it in api.get(f"/kits/{kid}/items").json()["items"]:
        assert kf["name"] not in it["field_mapping"]


# ---------------------------------------------------------------------------------------------------------
# Auto-detect com classificador semântico opcional (TypeSafe/Jev) — ver docs/DECISIONS.md D24. Um "dublê"
# local substitui a chamada HTTP real (essa parte já é testada em test_kit_role_classifier.py) para exercitar
# só a integração: como o resultado do classificador chega até os KitFields criados.


class _FakeRoleClassifier:
    """Classifica cada candidato por (nome do gerador, rótulo do campo) — sem HTTP nenhum. `by_label` cobre o
    caso comum (rótulo já basta); `by_generator_and_label` desambigua quando o MESMO rótulo aparece em mais
    de um gerador com papéis diferentes (ex.: dois geradores que já têm, cada um, seu próprio "Nome do
    contratante" — o rótulo sozinho não diz qual ocorrência o teste quer direcionar para outro papel)."""

    def __init__(
        self,
        by_label: dict[str, tuple[str, str | None]] | None = None,
        by_generator_and_label: dict[tuple[str, str], tuple[str, str | None]] | None = None,
        low_confidence_labels: set[str] | None = None,
        fail: bool = False,
    ) -> None:
        self.by_label = by_label or {}
        self.by_generator_and_label = by_generator_and_label or {}
        self.low_confidence_labels = low_confidence_labels or set()
        self.fail = fail
        self.calls = 0

    def classify(self, candidates):
        self.calls += 1
        if self.fail:
            raise RoleClassifierUnavailable("TYPESAFE_TIMEOUT", "indisponível no momento")
        out = {}
        for c in candidates:
            role, attr = self.by_generator_and_label.get(
                (c.generator_name, c.field.label), self.by_label.get(c.field.label, ("nao_e_parte", None))
            )
            conf = 0.3 if c.field.label in self.low_confidence_labels else 0.9
            out[c.id] = RoleAnswer(
                role=role, role_confidence=conf, attribute=attr, attribute_confidence=conf if attr else None
            )
        return out


def test_auto_detect_via_role_classifier_keeps_different_party_roles_apart(api, demo_docx, monkeypatch):
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    # os dois geradores ganham um segundo nome de pessoa — o da CONTRAPARTE, não o do contratante
    for gid in (gid_a, gid_b):
        r = api.post(f"/generators/{gid}/fields", json={"label": "Nome do contratado", "type": "text_short"})
        assert r.status_code == 201, r.text

    fake = _FakeRoleClassifier(
        by_label={
            "Nome do contratante": ("parte_a", "nome"),
            "Nome do contratado": ("parte_b", "nome"),
        }
    )
    monkeypatch.setattr("app.modules.kits.service.get_role_classifier", lambda: fake)

    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    r = api.post(f"/kits/{kid}/auto-detect")
    assert r.status_code == 200 and r.json()["provider"] == "typesafe" and fake.calls == 1

    fields = api.get(f"/kits/{kid}/fields").json()["items"]
    labels = {f["label"] for f in fields}
    # "Nome do contratante" e "Nome do contratado" viram DOIS campos do kit, nunca um só (são pessoas diferentes)
    assert {"Nome do contratante", "Nome do contratado"} <= labels
    for it in api.get(f"/kits/{kid}/items").json()["items"]:
        mapped_labels = {f["label"] for f in it["fields"] if f["name"] in it["field_mapping"].values()}
        assert {"Nome do contratante", "Nome do contratado"} <= mapped_labels


def test_auto_detect_via_role_classifier_merges_synonym_labels(api, demo_docx, monkeypatch):
    """ "Nome completo" (só existe no gerador B, rótulo diferente) e "Nome do contratante" (gerador A) são a
    MESMA pessoa segundo o classificador — viram um único campo do kit, algo que a similaridade de texto
    pura (D24 original) não faria (ver test_role_based_grouping_merges_synonyms... em test_kit_matching.py)."""
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    r = api.post(f"/generators/{gid_b}/fields", json={"label": "Nome completo", "type": "text_short"})
    assert r.status_code == 201, r.text

    fake = _FakeRoleClassifier(
        by_label={"Nome do contratante": ("parte_a", "nome"), "Nome completo": ("parte_a", "nome")},
        # gen B já tem SEU PRÓPRIO "Nome do contratante" (vem do demo_docx, igual ao de gen A); sem isto ele
        # competiria pela mesma vaga de "Nome completo" dentro do próprio gerador B e uma das duas cairia
        # fora (nunca dois campos do mesmo gerador no mesmo grupo) — aqui o teste quer mesmo é "Nome completo".
        by_generator_and_label={("Contrato B", "Nome do contratante"): ("nao_e_parte", None)},
    )
    monkeypatch.setattr("app.modules.kits.service.get_role_classifier", lambda: fake)

    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    api.post(f"/kits/{kid}/auto-detect")

    items = api.get(f"/kits/{kid}/items").json()["items"]
    item_a = next(it for it in items if it["generator_id"] == gid_a)
    item_b = next(it for it in items if it["generator_id"] == gid_b)
    field_a = next(f["name"] for f in item_a["fields"] if f["label"] == "Nome do contratante")
    field_b = next(f["name"] for f in item_b["fields"] if f["label"] == "Nome completo")
    kit_field_names_a = {
        name for name, member_field in item_a["field_mapping"].items() if member_field == field_a
    }
    kit_field_names_b = {
        name for name, member_field in item_b["field_mapping"].items() if member_field == field_b
    }
    assert kit_field_names_a and kit_field_names_a == kit_field_names_b  # mapeados ao MESMO campo do kit


def test_auto_detect_via_role_classifier_falls_back_to_similarity_for_low_confidence_fields(
    api, demo_docx, monkeypatch
):
    """Regressão real encontrada testando de verdade contra a TypeSafe: um rótulo IDÊNTICO nos dois
    documentos ("Nome completo", sem dizer de quem) pode deixar o classificador em dúvida sobre o papel —
    sem o caminho híbrido, isso faria o auto-detect regredir em relação ao D24 original (que juntaria
    trivialmente por serem rótulos idênticos). Aqui o classificador simula essa indecisão de propósito."""
    api.register()
    gid_a = build_generator(api, demo_docx, name="Contrato A")["id"]
    gid_b = build_generator(api, demo_docx, name="Contrato B")["id"]
    for gid in (gid_a, gid_b):
        r = api.post(f"/generators/{gid}/fields", json={"label": "Nome completo", "type": "text_short"})
        assert r.status_code == 201, r.text

    fake = _FakeRoleClassifier(
        by_label={"Nome completo": ("parte_a", "nome")}, low_confidence_labels={"Nome completo"}
    )
    monkeypatch.setattr("app.modules.kits.service.get_role_classifier", lambda: fake)

    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    r = api.post(f"/kits/{kid}/auto-detect")
    assert r.status_code == 200 and r.json()["provider"] == "typesafe"

    fields = api.get(f"/kits/{kid}/fields").json()["items"]
    assert "Nome completo" in {f["label"] for f in fields}  # juntado mesmo sem confiança do classificador
    for it in api.get(f"/kits/{kid}/items").json()["items"]:
        nome_completo_name = next(f["name"] for f in it["fields"] if f["label"] == "Nome completo")
        assert nome_completo_name in it["field_mapping"].values()


def test_auto_detect_falls_back_to_local_heuristic_when_classifier_is_unavailable(
    api, demo_docx, monkeypatch
):
    fake = _FakeRoleClassifier({}, fail=True)
    monkeypatch.setattr("app.modules.kits.service.get_role_classifier", lambda: fake)
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})

    r = api.post(f"/kits/{kid}/auto-detect")
    assert r.status_code == 200, r.text
    body = r.json()
    assert fake.calls == 1 and body["provider"] == "similarity"
    # mesmo resultado da heurística local sem classificador nenhum (comportamento inalterado, só degradado)
    assert body["created_fields"] == 5


def test_auto_detect_uses_local_heuristic_when_no_classifier_is_configured(api, demo_docx, monkeypatch):
    monkeypatch.setattr("app.modules.kits.service.get_role_classifier", lambda: None)
    api.register()
    gid_a, gid_b = _two_generators(api, demo_docx)
    kid = _new_kit(api)
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_a})
    api.post(f"/kits/{kid}/items", json={"generator_id": gid_b})
    r = api.post(f"/kits/{kid}/auto-detect")
    assert r.status_code == 200 and r.json()["provider"] == "similarity"

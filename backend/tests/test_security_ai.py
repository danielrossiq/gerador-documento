"""Segurança de upload (ZIP bomb, macros, path traversal, XXE), redação de logs e provedores de IA."""

from __future__ import annotations

import io
import json
import logging
import zipfile

import httpx
import pytest

from app.adapters.ai.anthropic import AnthropicMessagesProvider
from app.adapters.ai.base import AISuggestionRequest, AIUnavailable, BlockText
from app.core.logging import redact
from app.docx_engine.safety import DocxRejected, validate_docx
from tests.flows import upload

MB = 1024 * 1024


def _rewrite(docx: bytes, mutate) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            z.writestr(info.filename, src.read(info.filename))
        mutate(z)
    return out.getvalue()


def _check(data: bytes, name: str = "x.docx") -> str:
    with pytest.raises(DocxRejected) as exc:
        validate_docx(data, filename=name, max_bytes=15 * MB)
    return exc.value.code


def test_valid_docx_passes(demo_docx):
    info = validate_docx(demo_docx, filename="ok.docx", max_bytes=15 * MB)
    assert info.has_images and info.has_headers


def test_rejects_zip_bomb(demo_docx):
    bomb = _rewrite(demo_docx, lambda z: z.writestr("word/media/lixo.bin", b"\0" * (20 * MB)))
    assert len(bomb) < 100_000  # compacta ~200.000x: pequeno no disco, gigante descomprimido
    assert _check(bomb) == "ZIP_BOMB"


def test_rejects_macros(demo_docx):
    assert (
        _check(_rewrite(demo_docx, lambda z: z.writestr("word/vbaProject.bin", b"macro")))
        == "MACROS_NOT_ALLOWED"
    )

    def macro_ct(z):
        z.writestr(
            "[Content_Types].xml",
            b'<Types><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>',
        )

    src = zipfile.ZipFile(io.BytesIO(demo_docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            if info.filename != "[Content_Types].xml":
                z.writestr(info.filename, src.read(info.filename))
        macro_ct(z)
    assert _check(out.getvalue()) == "MACROS_NOT_ALLOWED"


def test_rejects_path_traversal_and_executables(demo_docx):
    assert _check(_rewrite(demo_docx, lambda z: z.writestr("../../evil.xml", b"x"))) == "UNSAFE_PATH"
    assert (
        _check(_rewrite(demo_docx, lambda z: z.writestr("word/embeddings/setup.exe", b"MZ")))
        == "EXECUTABLE_CONTENT"
    )


def test_rejects_wrong_type_size_and_corruption(demo_docx):
    assert _check(b"%PDF-1.7 ...") == "NOT_A_DOCX"
    assert _check(demo_docx[:200]) in ("CORRUPT_ZIP", "NOT_A_DOCX")
    assert _check(demo_docx, "arquivo.doc") == "INVALID_EXTENSION"
    with pytest.raises(DocxRejected) as exc:
        validate_docx(demo_docx, filename="x.docx", max_bytes=1000)
    assert exc.value.code == "FILE_TOO_LARGE"
    xlsx_like = _rewrite(demo_docx, lambda z: None)
    src = zipfile.ZipFile(io.BytesIO(xlsx_like))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", src.read("[Content_Types].xml"))
    assert _check(out.getvalue()) == "NOT_A_DOCX"  # falta word/document.xml


def test_xxe_and_entity_expansion_are_blocked(api, demo_docx):
    evil = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>'
    src = zipfile.ZipFile(io.BytesIO(demo_docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            z.writestr(
                info.filename, evil if info.filename == "word/document.xml" else src.read(info.filename)
            )
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    r = upload(api, gid, out.getvalue())
    assert r.status_code == 422 and r.json()["error"]["code"] == "DOCX_PARSE_FAILED"


def test_upload_size_limit_via_api(api, demo_docx):
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    big = demo_docx + b"\0" * (16 * MB)
    r = upload(api, gid, big)
    assert r.status_code == 422 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_storage_key_is_random_and_original_untouched(api, demo_docx, env):
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    upload(api, gid, demo_docx, "../../etc/passwd.docx")
    files = [p for p in (env / "storage").rglob("*") if p.is_file()]
    assert files and all("passwd" not in str(p) and ".." not in p.name for p in files)
    originals = [p for p in files if p.read_bytes() == demo_docx]
    assert len(originals) == 1  # o original é guardado imutável, byte a byte


def test_log_redaction_masks_personal_data(caplog):
    text = "CPF 123.456.789-09, CNPJ 11.222.333/0001-81, e-mail ana@exemplo.com.br, tel (11) 91234-5678"
    red = redact(text)
    for secret in ("123.456.789-09", "11.222.333/0001-81", "ana@exemplo.com.br", "91234-5678"):
        assert secret not in red
    from app.core.logging import RedactFilter

    log = logging.getLogger("t")
    log.addFilter(RedactFilter())
    with caplog.at_level(logging.INFO, logger="t"):
        log.info("dados: %s", "123.456.789-09")
    assert "123.456.789-09" not in caplog.text


def test_audit_never_stores_sensitive_metadata(api, demo_docx):
    from sqlalchemy import select

    from app.db.models import AuditEvent
    from app.db.session import get_factory
    from tests.flows import SAMPLE_VALUES, build_generator

    api.register()
    gid = build_generator(api, demo_docx)["id"]
    api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES})
    with get_factory()() as db:
        events = db.scalars(select(AuditEvent)).all()
    actions = {e.action for e in events}
    assert {"auth.register", "template.upload", "generation.create"} <= actions
    blob = json.dumps([e.meta for e in events], default=str)
    assert "529.982.247-25" not in blob and "Maria Souza" not in blob


def test_rate_limit_on_login(api):
    api.register("rl@exemplo.test")
    codes = [
        api.post("/auth/login", json={"email": "rl@exemplo.test", "password": "errada"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes and codes[0] == 401


# ------------------------------------------------------------------ provedor de IA


def _provider(handler, **kw) -> AnthropicMessagesProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AnthropicMessagesProvider(
        "k", "https://ia.exemplo", "modelo-x", 5, kw.pop("retries", 2), sleep=lambda s: None, client=client
    )


REQ = AISuggestionRequest(
    [BlockText("body/p1", "Contrato com João da Silva no valor de R$ 100,00.", "Parágrafo 1")]
)
GOOD = {
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "suggestions": [
                        {
                            "block": "body/p1",
                            "text": "João da Silva",
                            "name": "nome",
                            "label": "Nome",
                            "type": "text_short",
                            "confidence": 0.9,
                            "reason": "nome",
                        },
                        {
                            "block": "body/p1",
                            "text": "x",
                            "name": "y",
                            "label": "Y",
                            "type": "TIPO_INVALIDO",
                            "confidence": 0.5,
                        },
                        {
                            "block": "body/p1",
                            "text": "z",
                            "name": "y",
                            "label": "Y",
                            "type": "cpf",
                            "confidence": 7,
                        },
                    ]
                }
            ),
        }
    ],
    "usage": {"input_tokens": 120, "output_tokens": 40},
}


def test_ai_provider_validates_schema_and_records_usage():
    res = _provider(lambda req: httpx.Response(200, json=GOOD)).suggest(REQ)
    assert [s.text for s in res.suggestions] == ["João da Silva"]  # inválidos descartados
    assert (res.tokens_in, res.tokens_out, res.chars_sent) == (
        120,
        40,
        len("[body/p1] (Parágrafo 1) " + REQ.blocks[0].text),
    )
    assert any("descartadas" in w for w in res.warnings)


def test_ai_provider_retries_transient_errors_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=GOOD)

    assert _provider(handler).suggest(REQ).suggestions and len(calls) == 3


def test_ai_provider_gives_up_after_limited_retries():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(AIUnavailable) as exc:
        _provider(handler, retries=2).suggest(REQ)
    assert exc.value.code == "AI_UNAVAILABLE" and len(calls) == 3


def test_ai_provider_timeout_and_no_retry_on_auth_error():
    def timeout(req):
        raise httpx.ReadTimeout("lento")

    with pytest.raises(AIUnavailable) as exc:
        _provider(timeout, retries=1).suggest(REQ)
    assert exc.value.code == "AI_TIMEOUT"
    calls = []

    def auth(req):
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(AIUnavailable) as exc2:
        _provider(auth).suggest(REQ)
    assert exc2.value.code == "AI_AUTH_FAILED" and len(calls) == 1


def test_ai_provider_rejects_non_json_and_truncates_long_documents():
    bad = {"content": [{"type": "text", "text": "isto não é json"}]}
    with pytest.raises(AIUnavailable) as exc:
        _provider(lambda r: httpx.Response(200, json=bad)).suggest(REQ)
    assert exc.value.code == "AI_INVALID_RESPONSE"
    sent = {}

    def capture(req):
        sent["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"suggestions": []}'}]})

    big = AISuggestionRequest([BlockText(f"body/p{i}", "x" * 100, "") for i in range(100)], max_chars=1000)
    res = _provider(capture).suggest(big)
    assert res.truncated and res.chars_sent <= 1000 and any("só o início" in w for w in res.warnings)
    assert sent["body"]["temperature"] == 0 and sent["body"]["model"] == "modelo-x"


def test_ai_provider_never_logs_document_content(caplog):
    with caplog.at_level(logging.DEBUG):
        _provider(lambda r: httpx.Response(200, json=GOOD)).suggest(REQ)
    assert "João da Silva" not in caplog.text and "R$ 100" not in caplog.text


class CountingProvider:
    name, model = "contador", "m1"

    def __init__(self, fail: bool = False) -> None:
        self.calls, self.fail = 0, fail

    def suggest(self, request):
        from app.adapters.ai.base import AISuggestionResult

        self.calls += 1
        if self.fail:
            raise AIUnavailable("AI_TIMEOUT", "indisponível")
        return AISuggestionResult([], self.name, self.model, 10, 5, 100, 5)


def test_analysis_reuses_result_when_hash_unchanged(api, demo_docx, monkeypatch):
    prov = CountingProvider()
    monkeypatch.setattr("app.modules.suggestions.service.get_ai_provider", lambda: prov)
    api.register()
    g1 = api.post("/generators", json={"name": "G1"}).json()["id"]
    upload(api, g1, demo_docx)
    assert prov.calls == 1
    g2 = api.post("/generators", json={"name": "G2"}).json()["id"]
    upload(api, g2, demo_docx)  # mesmo arquivo, mesmo workspace → reaproveita sem chamar a IA
    assert prov.calls == 1
    assert api.get(f"/generators/{g2}/suggestions").json()["analysis"]["reused"] is True
    api.post(f"/generators/{g2}/suggestions/analyze", json={"force": True})
    assert prov.calls == 2  # reanálise explícita chama de novo


def test_analysis_degrades_gracefully_when_ai_is_down(api, demo_docx, monkeypatch):
    monkeypatch.setattr(
        "app.modules.suggestions.service.get_ai_provider", lambda: CountingProvider(fail=True)
    )
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    upload(api, gid, demo_docx)
    data = api.get(f"/generators/{gid}/suggestions").json()
    assert data["analysis"]["status"] == "done" and "indisponível" in (data["analysis"]["error"] or "")
    assert any(
        g["suggested_name"] == "cpf_contratante" for g in data["items"]
    )  # regras determinísticas continuam


def test_ai_provider_selection_from_env(monkeypatch):
    from app.adapters.ai import get_ai_provider
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    reset_settings_cache()
    assert get_ai_provider().name == "local"
    monkeypatch.setenv("AI_API_KEY", "sk-teste")
    reset_settings_cache()
    assert get_ai_provider().name == "local"  # trava do piloto (D30): sem EXTERNAL_AI_ENABLED, a chave não basta
    monkeypatch.setenv("EXTERNAL_AI_ENABLED", "true")
    reset_settings_cache()
    assert get_ai_provider().name == "anthropic"
    monkeypatch.setenv("AI_PROVIDER", "none")
    reset_settings_cache()
    assert get_ai_provider() is None
    reset_settings_cache()

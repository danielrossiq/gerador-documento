"""Teste grátis na landing (D38): fluxo, travas de custo/abuso, IA com orçamento diário, claim e limpeza.

Sem rede: a OpenRouter e o Turnstile são simulados; qualquer chamada HTTP real derruba o teste.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import timedelta

import httpx
import pytest
from docx import Document

from app.adapters.ai.openrouter import ChatResult, OpenRouterChat
from app.core.config import reset_settings_cache
from tests import pdf_samples

FAKE_KEY = "sk-or-v1-" + "b" * 64


@pytest.fixture()
def no_network(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("chamada de rede real durante o teste")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr("app.modules.assist.ai.model_prices", lambda model: (1e-7, 4e-7))


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


def send(api, content: bytes, filename: str = "contrato.docx", **form: str):  # type: ignore[no-untyped-def]
    return api.post(
        "/public/trials", files={"file": (filename, content, "application/octet-stream")}, data=form
    )


def status(api, token: str):  # type: ignore[no-untyped-def]
    return api.get(f"/public/trials/{token}")


def _trial_rows():  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.db.models import Trial
    from app.db.session import get_factory

    with get_factory()() as db:
        return db.scalars(select(Trial)).all()


def test_config_is_public(api):
    cfg = api.get("/public/trials/config").json()
    assert cfg["enabled"] is True and cfg["max_mb"] == 5 and cfg["max_pages"] == 10
    assert cfg["turnstile_site_key"] is None  # sem o segredo, o widget nem aparece


def test_docx_trial_end_to_end_with_local_rules(api, demo_docx, no_network, caplog):
    caplog.set_level(logging.INFO)
    r = send(api, demo_docx)
    assert r.status_code == 202, r.text
    token = r.json()["token"]
    out = status(api, token).json()
    assert out["status"] == "done" and out["ai"] == "local" and out["error"] is None
    fields = out["result"]["fields"]
    by_name = {f["name"]: f for f in fields}
    cpf = next(f for f in fields if f["type"] == "cpf")
    assert cpf["sample"] == "123.456.789-09"
    assert any(f["type"] == "cnpj" for f in fields) and any(f["type"] == "currency" for f in fields)
    assert len(by_name) == len(fields)
    assert "hits" not in out["result"]  # os achados brutos ficam no servidor
    # a prévia é o mesmo JSON do editor, com os campos como nós "field"
    doc_json = json.dumps(out["result"]["doc"])
    assert '"type": "field"' in doc_json and cpf["id"] in doc_json
    # nada do conteúdo vai para o log
    assert "123.456.789-09" not in caplog.text and "Silva" not in caplog.text
    row = _trial_rows()[0]
    assert row.token_hash != token and len(row.token_hash) == 64  # só o hash fica guardado


def test_trial_disabled(api, monkeypatch, demo_docx):
    _env(monkeypatch, TRIAL_ENABLED="false")
    r = send(api, demo_docx)
    assert r.status_code == 503 and r.json()["error"]["code"] == "TRIAL_DISABLED"
    assert api.get("/public/trials/config").json()["enabled"] is False


def test_disabled_by_default_in_production(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRIAL_ENABLED", raising=False)
    assert Settings().trials_on is False
    monkeypatch.setenv("TRIAL_ENABLED", "true")
    assert Settings().trials_on is True


def test_honeypot_looks_like_a_real_trial_that_failed(api, demo_docx, env):
    """Armadilha (F2-5): mesmo formato da resposta real; fica "processando" uns segundos e depois falha com a
    mensagem genérica. Nenhum arquivo é guardado nem processado."""
    from app.db.base import utcnow
    from app.db.models import Trial
    from app.db.session import get_factory

    r = send(api, demo_docx, website="http://spam.example")
    assert r.status_code == 202 and r.json()["status"] == "processing"
    assert set(r.json()) == set(send(api, demo_docx).json())  # mesmo formato da resposta real
    token = r.json()["token"]
    assert status(api, token).json()["status"] == "processing"
    with get_factory()() as db:
        decoy = db.query(Trial).filter(Trial.storage_key.is_(None)).one()
        decoy.finished_at = utcnow() - timedelta(seconds=1)
        db.commit()
    out = status(api, token).json()
    assert out["status"] == "failed" and out["error"]["code"] == "TRIAL_FAILED" and out["result"] is None
    assert len([t for t in _trial_rows() if t.storage_key]) == 1  # só o envio de verdade tem arquivo
    assert len([p for p in (env / "storage").rglob("*") if p.is_file()]) == 1


def test_malformed_multipart_is_a_typed_400(api):
    body = b"--XYZ\r\nisto nao e um cabecalho\r\n\r\nabc\r\n--XYZ--\r\n"
    r = api.post(
        "/public/trials",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=XYZ", "Content-Length": str(len(body))},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "TRIAL_FORM_INVALID"


def test_corrupt_docx_on_the_public_route_is_422(api):
    from tests.test_qa_robustness import _corrupt_member, _docx

    bad = _corrupt_member(_docx(["Contrato de teste."]), "[Content_Types].xml")
    r = send(api, bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "CORRUPT_ZIP"


def test_paragraph_full_of_patterns_does_not_hold_the_worker(api):
    """QA-4: um parágrafo de ~38 mil caracteres com ~3.600 achados prendia o worker por 112 s."""
    import time

    doc = Document()
    doc.add_paragraph("01/10/2026 529.982.247-25 R$ 1,00 29101-000 " * 860)
    buf = io.BytesIO()
    doc.save(buf)
    t = time.perf_counter()
    out = status(api, send(api, buf.getvalue()).json()["token"]).json()
    assert time.perf_counter() - t < 15
    assert out["status"] == "done"
    total = sum(f["count"] for f in out["result"]["fields"])
    assert 0 < total <= 30  # um parágrafo: no máximo 30 achados viram campo na prévia


@pytest.mark.parametrize(
    ("content", "name", "code"),
    [
        (b"", "vazio.docx", "EMPTY_FILE"),
        (b"texto qualquer, nada de Word", "nota.txt", "TRIAL_FILE_TYPE"),
        (b"\xd0\xcf\x11\xe0" + b"\0" * 600, "antigo.doc", "TRIAL_FILE_TYPE"),
        (b"PK\x03\x04quebrado", "quebrado.docx", None),  # zip inválido: recusado pelo validate_docx
    ],
)
def test_bad_files_are_refused_before_anything_is_stored(api, content, name, code):
    r = send(api, content, name)
    assert r.status_code == 422, r.text
    if code:
        assert r.json()["error"]["code"] == code
    assert _trial_rows() == []


def test_size_is_checked_from_content_length_before_reading(api):
    big = b"PK" + b"0" * (5 * 1024 * 1024 + 100_000)
    r = send(api, big, "grande.docx")
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_long_document_is_refused(api):
    doc = Document()
    for _ in range(120):
        doc.add_paragraph("Cláusula de exemplo com texto corrido. " * 10)
    buf = io.BytesIO()
    doc.save(buf)
    token = send(api, buf.getvalue()).json()["token"]
    out = status(api, token).json()
    assert out["status"] == "failed" and out["error"]["code"] == "TRIAL_TOO_LONG"
    assert "10 páginas" in out["error"]["message"]


def test_typed_pdf_is_converted_and_analyzed(api):
    r = send(api, pdf_samples.typed_pdf(), "contrato.pdf")
    assert r.status_code == 202, r.text
    out = status(api, r.json()["token"]).json()
    assert out["status"] == "done" and out["format"] == "pdf"
    assert any(f["type"] == "cpf" for f in out["result"]["fields"])
    row = _trial_rows()[0]
    assert row.storage_key.endswith(".docx")  # o PDF original já foi trocado pelo .docx convertido


def test_scanned_pdf_fails_with_the_usual_message(api):
    out = status(api, send(api, pdf_samples.scanned_pdf(), "foto.pdf").json()["token"]).json()
    assert out["status"] == "failed" and out["error"]["code"] == "PDF_SCANNED"


def test_pdf_refused_when_pdf_import_is_off(api, monkeypatch):
    _env(monkeypatch, PDF_IMPORT_ENABLED="false")
    r = send(api, pdf_samples.typed_pdf(), "contrato.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "PDF_IMPORT_DISABLED"
    assert api.get("/public/trials/config").json()["accepts_pdf"] is False


def test_rate_limit_per_ip_per_hour(app, demo_docx):
    from fastapi.testclient import TestClient

    with TestClient(app, client=("198.51.100.7", 4000)) as tc:
        codes = [
            tc.post("/api/v1/public/trials", files={"file": ("c.docx", demo_docx)}).status_code
            for _ in range(4)
        ]
    assert codes == [202, 202, 202, 429]
    with TestClient(app, client=("203.0.113.8", 4000)) as tc:  # outro IP continua podendo
        assert tc.post("/api/v1/public/trials", files={"file": ("c.docx", demo_docx)}).status_code == 202


def test_rate_limit_per_network(app, monkeypatch, demo_docx):
    from fastapi.testclient import TestClient

    _env(monkeypatch, TRIAL_LIMIT_NET_DAY="2")
    codes = []
    for host in ("198.51.100.7", "198.51.100.8", "198.51.100.9"):  # mesma /24
        with TestClient(app, client=(host, 4000)) as tc:
            r = tc.post("/api/v1/public/trials", files={"file": ("c.docx", demo_docx)})
            codes.append((r.status_code, r.json().get("error", {}).get("code")))
    assert codes[:2] == [(202, None), (202, None)] and codes[2] == (429, "TRIAL_RATE_LIMITED")


def test_spoofed_forwarded_for_does_not_reset_the_limit(app, demo_docx):
    from fastapi.testclient import TestClient

    with TestClient(app, client=("203.0.113.40", 4000)) as tc:  # chamada direta, sem passar pelo Next
        codes = [
            tc.post(
                "/api/v1/public/trials",
                files={"file": ("c.docx", demo_docx)},
                headers={"X-Forwarded-For": f"10.9.8.{i}"},
            ).status_code
            for i in range(4)
        ]
    assert codes[-1] == 429


def test_max_concurrent_trials(api, monkeypatch, demo_docx):
    import time

    _env(monkeypatch, TRIAL_MAX_CONCURRENT="1", TRIAL_BUSY_WAIT_SECONDS="1")
    monkeypatch.setattr("app.modules.trials.service.enqueue", lambda *a, **k: None)  # fica na fila
    assert send(api, demo_docx).status_code == 202
    started = time.monotonic()
    r = send(api, demo_docx)
    assert r.status_code == 429 and r.json()["error"]["code"] == "TRIAL_BUSY"
    assert time.monotonic() - started >= 1  # esperou por uma vaga antes de recusar (fila curta)
    assert len(_trial_rows()) == 1  # o arquivo recusado não ficou guardado


def test_stale_trial_does_not_hold_a_slot(api, monkeypatch, demo_docx):
    from app.db.base import utcnow
    from app.db.models import Trial
    from app.db.session import get_factory

    _env(monkeypatch, TRIAL_MAX_CONCURRENT="1", TRIAL_BUSY_WAIT_SECONDS="0")
    monkeypatch.setattr("app.modules.trials.service.enqueue", lambda *a, **k: None)
    token = send(api, demo_docx).json()["token"]
    with get_factory()() as db:
        t = db.query(Trial).one()
        t.status, t.created_at, t.started_at = (
            "processing",
            utcnow() - timedelta(minutes=6),
            utcnow() - timedelta(minutes=6),
        )
        db.commit()
    assert status(api, token).json()["status"] == "failed"  # o worker morreu: a pessoa não fica esperando
    assert send(api, demo_docx).status_code == 202


# ------------------------------------------------------------------ Turnstile


def _mock_siteverify(payload: dict | Exception):  # type: ignore[no-untyped-def]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        seen.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_turnstile_verify_formats():
    from app.modules.trials import turnstile

    client, seen = _mock_siteverify({"success": True, "action": "trial", "hostname": "docfeito.com.br"})
    assert turnstile.verify("tok", "198.51.100.7", secret="s3", client=client)
    assert (
        seen[0]["secret"] == "s3" and seen[0]["response"] == "tok" and seen[0]["remoteip"] == "198.51.100.7"
    )
    assert seen[0]["idempotency_key"]
    client, _ = _mock_siteverify({"success": True, "action": "login"})
    assert not turnstile.verify("tok", None, secret="s3", client=client)  # token de outra página
    client, _ = _mock_siteverify({"success": False, "error-codes": ["timeout-or-duplicate"]})
    assert not turnstile.verify("tok", None, secret="s3", client=client)
    client, _ = _mock_siteverify(httpx.ConnectError("fora do ar"))
    assert not turnstile.verify("tok", None, secret="s3", client=client)  # falha fechada
    assert not turnstile.verify("", None, secret="s3", client=client)
    assert not turnstile.verify("x" * 2049, None, secret="s3", client=client)


def test_turnstile_required_when_configured(api, monkeypatch, demo_docx):
    _env(monkeypatch, TURNSTILE_SECRET_KEY="segredo", TURNSTILE_SITE_KEY="site-123")
    assert api.get("/public/trials/config").json()["turnstile_site_key"] == "site-123"
    calls = []
    monkeypatch.setattr(
        "app.modules.trials.turnstile.verify",
        lambda token, ip, *, secret: calls.append((token, secret)) or token == "bom",
    )
    r = send(api, demo_docx)
    assert r.status_code == 403 and r.json()["error"]["code"] == "TRIAL_CHALLENGE_FAILED"
    assert send(api, demo_docx, turnstile_token="bom").status_code == 202
    assert calls[-1] == ("bom", "segredo")


# ------------------------------------------------------------------ IA com orçamento diário próprio


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(kw)
        data = {
            "suggestions": [
                {
                    "block": "body/p3",
                    "text": "João da Silva",
                    "name": "nome_contratante",
                    "label": "Nome do contratante",
                    "type": "text_short",
                    "confidence": 0.95,
                    "reason": "parte do contrato",
                }
            ]
        }
        return ChatResult(
            data=data, model=kw["model"], tokens_in=900, tokens_out=120, cost_usd=0.0003, duration_ms=5
        )


@pytest.fixture()
def ai_on(monkeypatch: pytest.MonkeyPatch, no_network):  # type: ignore[no-untyped-def]
    _env(monkeypatch, EXTERNAL_AI_ENABLED="true", OPENROUTER_API_KEY=FAKE_KEY, AI_PROVIDER="openrouter")
    fake = FakeChat()
    monkeypatch.setattr(OpenRouterChat, "complete", fake)
    yield fake
    reset_settings_cache()


def _spend():  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.db.models import AISpend
    from app.db.session import get_factory

    with get_factory()() as db:
        return db.scalars(select(AISpend)).all()


def test_ai_reads_only_the_start_and_is_charged_to_the_trial_budget(api, demo_docx, ai_on):
    out = status(api, send(api, demo_docx).json()["token"]).json()
    assert out["ai"] == "ai"
    names = {f["name"] for f in out["result"]["fields"]}
    assert "nome_contratante" in names
    sent = ai_on.calls[0]["user"]
    assert len(sent) <= 6000 + 200  # só o começo do documento (TRIAL_AI_MAX_CHARS)
    rows = _spend()
    assert len(rows) == 1 and rows[0].purpose == "trial" and rows[0].workspace_id is None
    assert rows[0].status == "settled"


def test_daily_budget_exhausted_falls_back_to_local_rules(api, demo_docx, ai_on, monkeypatch):
    _env(monkeypatch, TRIAL_AI_DAILY_BUDGET_USD="0.0000001")
    out = status(api, send(api, demo_docx).json()["token"]).json()
    assert out["status"] == "done" and out["ai"] == "budget"
    assert any(f["type"] == "cpf" for f in out["result"]["fields"])  # as regras seguem funcionando
    assert ai_on.calls == [] and _spend() == []


def test_ai_outage_falls_back_to_local(api, demo_docx, ai_on, monkeypatch):
    from app.adapters.ai.base import AIUnavailable

    def down(*a, **k):  # type: ignore[no-untyped-def]
        raise AIUnavailable("AI_TIMEOUT", "fora do ar")

    monkeypatch.setattr(OpenRouterChat, "complete", down)
    out = status(api, send(api, demo_docx).json()["token"]).json()
    assert out["status"] == "done" and out["ai"] == "local"
    assert [r.status for r in _spend()] == ["failed"]


def test_unbudgeted_external_provider_is_never_used_for_anonymous(api, demo_docx, monkeypatch, no_network):
    _env(monkeypatch, EXTERNAL_AI_ENABLED="true", AI_PROVIDER="anthropic", AI_API_KEY="sk-ant-teste")
    out = status(api, send(api, demo_docx).json()["token"]).json()
    assert out["status"] == "done" and out["ai"] == "local"


# ------------------------------------------------------------------ claim e limpeza


def test_claim_creates_the_model_with_suggestions(api, demo_docx, ai_on):
    token = send(api, demo_docx).json()["token"]
    assert api.post(f"/trials/{token}/claim").status_code == 401  # exige conta
    api.register()
    r = api.post(f"/trials/{token}/claim")
    assert r.status_code == 201, r.text
    gid = r.json()["generator_id"]
    assert r.json()["next"] == f"/generators/{gid}/edit"
    gen = api.get(f"/generators/{gid}").json()
    assert gen["name"] == "contrato"
    sug = api.get(f"/generators/{gid}/suggestions").json()
    names = {g["suggested_name"] for g in sug["items"]}
    assert "nome_contratante" in names and any("cpf" in n for n in names)
    assert sug["analysis"]["status"] == "done" and sug["analysis"]["provider"] == "openrouter"
    assert len(ai_on.calls) == 1  # nada de nova análise (nem custo) ao guardar
    # o teste deixa de existir: arquivo apagado e token sem efeito
    assert status(api, token).status_code == 404
    assert api.post(f"/trials/{token}/claim").status_code == 404
    row = _trial_rows()[0]
    assert row.storage_key is None and row.result is None and str(row.claimed_generator_id) == gid
    # a sugestão aceita aplica no documento normalmente
    first = sug["items"][0]["id"]
    assert api.post(f"/suggestions/{first}/accept", json={}).status_code == 200


def test_claim_respects_the_plan_limit_and_can_be_retried(api, demo_docx):
    from app.db.models import Workspace
    from app.db.session import get_factory

    token = send(api, demo_docx).json()["token"]
    me = api.register()
    with get_factory()() as db:
        ws = db.get(Workspace, __import__("uuid").UUID(me["workspace"]["id"]))
        ws.limits = {"max_generators": 0}
        db.commit()
    r = api.post(f"/trials/{token}/claim")
    assert r.status_code == 429 and r.json()["error"]["code"] == "GENERATOR_LIMIT"
    with get_factory()() as db:
        ws = db.get(Workspace, __import__("uuid").UUID(me["workspace"]["id"]))
        ws.limits = None
        db.commit()
    assert api.post(f"/trials/{token}/claim").status_code == 201


def test_expired_trial_is_gone_and_purged(api, demo_docx, env):
    from app.db.base import utcnow
    from app.db.models import Trial
    from app.db.session import get_factory
    from app.modules.trials.service import purge_expired_trials

    token = send(api, demo_docx).json()["token"]
    with get_factory()() as db:
        t = db.query(Trial).one()
        key = t.storage_key
        t.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    stored = env / "storage" / key
    assert stored.exists()
    assert status(api, token).status_code == 404
    api.register()
    assert api.post(f"/trials/{token}/claim").status_code == 404
    assert purge_expired_trials() == {"removidos": 1, "falhas": 0}
    assert _trial_rows() == [] and not stored.exists()


def test_bad_tokens(api):
    assert status(api, "curto").status_code == 404
    assert status(api, "x" * 43).json()["error"]["code"] == "TRIAL_NOT_FOUND"


def test_docx_that_expands_too_much_is_refused(api, demo_docx):
    """Visitante anônimo: no máximo 25 MB descompactados (as contas seguem com o limite de sempre)."""
    import os
    import zipfile

    noise = os.urandom(13 * 1024 * 1024).translate(bytes(48 + (i & 1) for i in range(256)))  # comprime ~8x
    buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(demo_docx)) as src,
        zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("word/media/a.bin", noise)
        dst.writestr("word/media/b.bin", noise)
    data = buf.getvalue()
    assert len(data) < 5 * 1024 * 1024
    r = send(api, data)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ZIP_BOMB"
    assert _trial_rows() == []


def test_turnstile_approved_gets_a_higher_hourly_limit(app, monkeypatch, demo_docx):
    """CGNAT de celular (F2-3): com o desafio aprovado, 6 por hora por IP; sem ele, 3. O /24 continua valendo."""
    from fastapi.testclient import TestClient

    _env(monkeypatch, TURNSTILE_SECRET_KEY="segredo", TRIAL_MAX_CONCURRENT="50")
    monkeypatch.setattr("app.modules.trials.turnstile.verify", lambda token, ip, *, secret: token == "bom")
    monkeypatch.setattr("app.modules.trials.service.enqueue", lambda *a, **k: None)
    with TestClient(app, client=("198.51.100.20", 4000)) as tc:
        codes = [
            tc.post(
                "/api/v1/public/trials",
                files={"file": ("c.docx", demo_docx)},
                data={"turnstile_token": "bom"},
            ).status_code
            for _ in range(7)
        ]
    assert codes == [202] * 6 + [429]


def test_honeypot_with_a_bad_file_gets_the_usual_refusal(api):
    r = send(api, b"isto nao e documento", "x.txt", website="http://spam.example")
    assert r.status_code == 422 and r.json()["error"]["code"] == "TRIAL_FILE_TYPE"  # igual a quem não é robô


def test_busy_without_free_waiting_slots_refuses_at_once(api, monkeypatch, demo_docx):
    import threading
    import time

    _env(monkeypatch, TRIAL_MAX_CONCURRENT="1", TRIAL_BUSY_WAIT_SECONDS="5")
    monkeypatch.setattr("app.modules.trials.service.enqueue", lambda *a, **k: None)
    monkeypatch.setattr("app.modules.trials.service._WAITING", threading.BoundedSemaphore(1))
    from app.modules.trials import service

    assert send(api, demo_docx).status_code == 202
    service._WAITING.acquire()  # a única vaga de espera já está ocupada
    started = time.monotonic()
    r = send(api, demo_docx)
    assert r.status_code == 429 and r.json()["error"]["code"] == "TRIAL_BUSY"
    assert time.monotonic() - started < 2  # não esperou: não prende thread do pool


def test_orphaned_trials_do_not_hold_slots_and_busy_does_not_spend_the_hourly_limit(api, monkeypatch, demo_docx):
    """QA-6: teste preso em "processing" sem heartbeat (API/worker reiniciado) não ocupa vaga e é encerrado; e
    TRIAL_BUSY não desconta do limite por hora."""
    from app.db.base import utcnow
    from app.db.models import Trial
    from app.db.session import get_factory
    from app.modules.trials.service import fail_orphaned_trials

    _env(monkeypatch, TRIAL_MAX_CONCURRENT="1", TRIAL_BUSY_WAIT_SECONDS="0")
    monkeypatch.setattr("app.modules.trials.service.enqueue", lambda *a, **k: None)
    first = send(api, demo_docx).json()["token"]  # 1ª tentativa (fica na fila e ocupa a vaga)
    for _ in range(3):  # vaga ocupada: recusa sem gastar a vez
        assert send(api, demo_docx).json()["error"]["code"] == "TRIAL_BUSY"
    with get_factory()() as db:  # o processo que segurava o teste morreu: heartbeat velho
        t = db.query(Trial).one()
        t.status, t.heartbeat_at = "processing", utcnow() - timedelta(minutes=1)
        db.commit()
    assert fail_orphaned_trials() == 1
    assert status(api, first).json()["status"] == "failed"
    assert send(api, demo_docx).status_code == 202  # 2ª tentativa
    with get_factory()() as db:
        for t in db.query(Trial).filter(Trial.status == "queued"):
            t.status = "failed"
        db.commit()
    assert send(api, demo_docx).status_code == 202  # 3ª
    with get_factory()() as db:
        for t in db.query(Trial).filter(Trial.status == "queued"):
            t.status = "failed"
        db.commit()
    assert send(api, demo_docx).json()["error"]["code"] == "TRIAL_RATE_LIMITED"  # 4ª: aí sim o limite de 3/h

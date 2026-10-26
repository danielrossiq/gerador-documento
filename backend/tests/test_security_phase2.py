"""Regressões de segurança da revisão da D38 (teste grátis), fase 2 da segurança.

Sem rede. Cada teste aponta o achado de docs/SEGURANCA_SPRINT.md (seção "Fase 2") que ele protege.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

TOKEN = "Zq3v" + "A" * 39  # formato do token do teste (43 caracteres base64url), valor fictício


# ---------------------------------------------------------------- F2-1: token do teste no log de acesso


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/public/trials/{TOKEN}",
        f"/api/v1/trials/{TOKEN}/claim",
        f"/api/v1/public/requests/{TOKEN}",
        f"/api/v1/public/requests/{TOKEN}/fill-files",
        f"/api/v1/signatures/webhook/zapsign/{TOKEN}",
    ],
)
def test_token_do_teste_nao_vai_para_o_log(path: str) -> None:
    from app.core.logging import _safe_extra

    assert TOKEN not in _safe_extra("path", path)


# ---------------------------------------------------------------- F2-2: falha forçada da IA x teto diário


def test_falha_da_ia_conta_no_teto_diario_do_teste_e_nao_no_mensal(api, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Forçar a IA a falhar não dá chamadas grátis: a reserva da falha continua no teto diário do teste, e o gasto
    do teste fica fora do teto mensal que protege os clientes (OBR-5)."""
    from app.core.config import reset_settings_cache
    from app.db.session import get_factory
    from app.modules import ai_budget

    monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "0.05")
    reset_settings_cache()
    cap = Decimal("0.05")
    for _ in range(2):
        ai_budget.fail(ai_budget.reserve("m", "trial", Decimal("0.02"), daily_cap_usd=cap))
    with pytest.raises(ai_budget.BudgetExceeded) as exc:
        ai_budget.reserve("m", "trial", Decimal("0.02"), daily_cap_usd=cap)
    assert exc.value.code == "AI_DAILY_BUDGET_EXHAUSTED"
    with get_factory()() as db:
        assert ai_budget.spent_today(db, "trial") == Decimal("0.04")
        assert ai_budget.spent_this_month(db) == 0
    # o teto mensal dos clientes continua inteiro mesmo com o do teste esgotado
    ai_budget.reserve("m", "fill", Decimal("0.04"))
    reset_settings_cache()


# ---------------------------------------------------------------- F2-3: claim por outra conta


def test_teste_ja_guardado_nao_pode_ser_tomado_por_outra_conta(api, api2, demo_docx) -> None:  # type: ignore[no-untyped-def]
    token = api.post(
        "/public/trials", files={"file": ("contrato.docx", demo_docx, "application/octet-stream")}
    ).json()["token"]
    api.register()
    first = api.post(f"/trials/{token}/claim")
    assert first.status_code == 201, first.text
    api2.register()
    assert api2.post(f"/trials/{token}/claim").status_code == 404
    assert api2.get("/generators").json()["total"] == 0


# ---------------------------------------------------------------- B (D39): link do cliente, página /r/{token}
# Revisão de segurança da B: OBR-6 (token), OBR-7 (limites e anexos), OBR-8 (XSS/CSP), OBR-9 (só os campos
# pedidos), REC-6 (custo de PDF) e DEP-1 (PDF de fora nunca aberto na API).

FAKE_AI_KEY = "sk-or-v1-" + "d" * 64


def _link(api, demo_docx, **body):  # type: ignore[no-untyped-def]
    from tests.flows import build_generator

    api.register()
    gid = build_generator(api, demo_docx)["id"]
    r = api.post(f"/generators/{gid}/client-requests", json=body)
    assert r.status_code == 201, r.text
    return r.json(), r.json()["url"].rsplit("/r/", 1)[1]


def _row(rid: str):  # type: ignore[no-untyped-def]
    import uuid

    from app.db.models import ClientRequest
    from app.db.session import get_factory

    with get_factory()() as db:
        return db.get(ClientRequest, uuid.UUID(rid))


def _image(fmt: str, w: int, h: int) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("L" if fmt == "PNG" else "RGB", (w, h), 200).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture()
def fake_ai(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """IA simulada e rede bloqueada: qualquer HTTP real derruba o teste."""
    import httpx

    from app.adapters.ai.openrouter import ChatResult, OpenRouterChat
    from app.core.config import reset_settings_cache

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("chamada de rede real durante o teste")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr("app.modules.assist.ai.model_prices", lambda model: (1e-7, 4e-7))
    monkeypatch.setenv("EXTERNAL_AI_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_AI_KEY)
    reset_settings_cache()
    calls: list[dict] = []

    def complete(*args, **kw):  # type: ignore[no-untyped-def]
        calls.append(kw)
        return ChatResult(
            data={"values": [], "documents": ["RG"]},
            model=kw["model"],
            tokens_in=900,
            tokens_out=50,
            cost_usd=0.0003,
            duration_ms=5,
        )

    monkeypatch.setattr(OpenRouterChat, "complete", complete)
    yield calls
    reset_settings_cache()


def test_link_guarda_so_o_hash_e_responde_404_igual(api, api2, demo_docx) -> None:  # type: ignore[no-untyped-def]
    """OBR-6: o token (32 bytes) não fica no banco, só o SHA-256; token inexistente, malformado ou de link
    cancelado devolvem o mesmo 404, sem dizer qual é o caso."""
    import hashlib

    out, token = _link(api, demo_docx, message="Oi")
    assert len(token) >= 43
    row = _row(out["id"])
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str({c.name: getattr(row, c.name) for c in row.__table__.columns})

    def gone(t: str):  # type: ignore[no-untyped-def]
        r = api2.get(f"/public/requests/{t}")
        return r.status_code, r.json()["error"]["code"], r.json()["error"]["message"]

    other = "B" * 43  # formato válido, nunca emitido
    assert gone(other) == gone("curto") == gone(token[:-1] + "%2F")
    assert api.post(f"/client-requests/{out['id']}/cancel").status_code == 200
    assert gone(token) == gone(other)
    assert gone(other)[0] == 404


def test_token_do_link_nao_vai_para_o_log_de_acesso(app, demo_docx, api, caplog) -> None:  # type: ignore[no-untyped-def]
    """O log de acesso da API (logger app.http) formatado como em produção não leva o token do link."""
    import logging

    from app.core.logging import JsonFormatter

    _, token = _link(api, demo_docx)
    caplog.set_level(logging.INFO, logger="app.http")
    api.get(f"/public/requests/{token}")
    api.post(f"/public/requests/{token}", json={"values": {}})
    lines = [JsonFormatter().format(r) for r in caplog.records if r.name == "app.http"]
    assert lines and all(token not in line for line in lines)
    assert any("/public/requests/[token]" in line for line in lines)


def test_enumerar_tokens_esbarra_no_limite_por_ip(app, api, demo_docx) -> None:  # type: ignore[no-untyped-def]
    """Tentativas com token errado contam no limite por IP (a conta é feita antes de procurar o link): quem varre
    tokens é barrado no mesmo ritmo de quem abre a página. Com 256 bits, adivinhar já é inviável; isto corta o
    ruído e o custo de banco."""
    from fastapi.testclient import TestClient

    _, token = _link(api, demo_docx)
    with TestClient(app, client=("198.51.100.77", 4000)) as tc:
        codes = [tc.get(f"/api/v1/public/requests/{i:043d}").status_code for i in range(60)]
        assert set(codes) == {404}
        assert tc.get(f"/api/v1/public/requests/{token}").status_code == 429  # nem o token certo passa


def test_envio_publico_tem_teto_de_corpo_antes_de_ler_o_json(app, api, demo_docx) -> None:  # type: ignore[no-untyped-def]
    """O envio do cliente é público: corpo acima do teto é recusado pelo Content-Length, sem ler nem
    interpretar o JSON (mesmo com token inválido); JSON quebrado vira 400 tipado."""
    from fastapi.testclient import TestClient

    from app.modules.requests.service import SUBMIT_MAX_BYTES

    _, token = _link(api, demo_docx)
    big = b'{"values": {"x": "' + b"a" * SUBMIT_MAX_BYTES + b'"}}'
    with TestClient(app) as tc:
        for t in (token, "C" * 43):
            r = tc.post(
                f"/api/v1/public/requests/{t}", content=big, headers={"Content-Type": "application/json"}
            )
            assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
        r = tc.post(
            f"/api/v1/public/requests/{token}", content=b"{quebrado", headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400 and r.json()["error"]["code"] == "FORM_INVALID"
        r = tc.post(f"/api/v1/public/requests/{token}", json={"values": ["lista"]})
        assert r.status_code == 400 and r.json()["error"]["code"] == "FORM_INVALID"


def test_fotos_pelo_link_seguem_os_limites_da_d37(api, api2, demo_docx, fake_ai, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OBR-7: PNG/WEBP acima de 16 Mpx é recusado antes da IA e não gasta a leitura do link; JPEG grande é
    decodificado já reduzido (`draft`) e chega à IA com no máximo 2.000 px de lado, sem metadados."""
    import base64
    import io

    from PIL import Image, JpegImagePlugin

    out, token = _link(api, demo_docx, fields=["cpf_do_contratante"], allow_photos=True)
    png = _image("PNG", 4100, 4000)  # 16,4 Mpx
    r = api2.post(f"/public/requests/{token}/fill-files", files=[("files", ("doc.png", png, "image/png"))])
    assert r.status_code == 422 and r.json()["error"]["code"] == "AI_FILE_INVALID"
    assert fake_ai == [] and _row(out["id"]).photo_reads == 0

    drafts: list[tuple] = []
    real_draft = JpegImagePlugin.JpegImageFile.draft

    def spy(self, mode, size):  # type: ignore[no-untyped-def]
        drafts.append(size)
        return real_draft(self, mode, size)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", spy)
    jpg = _image("JPEG", 4800, 3600)
    r = api2.post(f"/public/requests/{token}/fill-files", files=[("files", ("doc.jpg", jpg, "image/jpeg"))])
    assert r.status_code == 200, r.text
    assert drafts == [(2000, 2000)]
    sent = fake_ai[0]["attachments"][0]["image_url"]["url"].split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(sent))) as im:
        assert max(im.size) <= 2000 and not im.getexif()
    assert _row(out["id"]).photo_reads == 1


def test_pdf_pelo_link_e_contado_no_pdfconv_e_nunca_aberto_na_api(api, api2, demo_docx, fake_ai, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """DEP-1/REC-6: com o conversor isolado configurado, as páginas do PDF vêm do pdfconv (`/info`); a API não
    abre o PDF (nem pdfplumber, nem pdfium, nem processo filho). Mais de 10 páginas é recusado sem gastar a
    leitura, e a reserva de custo usa a contagem real."""
    import pdfplumber
    import pypdfium2

    from app.core.config import reset_settings_cache
    from app.docx_engine import pdf_import

    def never(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("PDF de fora aberto dentro da API")

    monkeypatch.setattr(pdfplumber, "open", never)
    monkeypatch.setattr(pypdfium2, "PdfDocument", never)
    monkeypatch.setattr(pdf_import, "pdf_info_isolated", never)
    asked: list[str] = []
    pages = {"n": 11}

    def info_remote(data: bytes, *, url: str, client=None):  # type: ignore[no-untyped-def]
        asked.append(url)
        return {"pages": pages["n"]}

    monkeypatch.setattr(pdf_import, "pdf_info_remote", info_remote)
    monkeypatch.setenv("PDF_CONVERTER_URL", "http://pdfconv:8000")
    reset_settings_cache()

    out, token = _link(api, demo_docx, fields=["cpf_do_contratante"], allow_photos=True)
    pdf = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"
    files = [("files", ("doc.pdf", pdf, "application/pdf"))]
    r = api2.post(f"/public/requests/{token}/fill-files", files=files)
    assert r.status_code == 422 and r.json()["error"]["code"] == "AI_PDF_TOO_MANY_PAGES"
    assert asked == ["http://pdfconv:8000"] and fake_ai == [] and _row(out["id"]).photo_reads == 0

    pages["n"] = 2
    captured: list[int] = []
    from app.modules.assist import ai

    real_worst = ai.worst_cost

    def worst(model, chars, max_tokens, extra=0):  # type: ignore[no-untyped-def]
        captured.append(extra)
        return real_worst(model, chars, max_tokens, extra)

    monkeypatch.setattr(ai, "worst_cost", worst)
    assert api2.post(f"/public/requests/{token}/fill-files", files=files).status_code == 200
    assert captured == [2 * 1500]  # 2 páginas x PDF_TOKENS_PER_PAGE
    assert fake_ai[0]["attachments"][0]["type"] == "file"  # o PDF vai inteiro para a IA ler, sem abrir aqui


def test_link_invalido_nao_recebe_os_arquivos(app, api, demo_docx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """O `fill-files` confere limite por IP e o link (existe, está aberto, aceita fotos) ANTES de ler o
    multipart: com token errado ou link sem fotos, a API não recebe os até 24 MB do corpo."""
    from starlette.requests import Request

    _, token = _link(api, demo_docx)  # link sem fotos

    async def never(self, *a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("corpo lido antes de validar o link")

    monkeypatch.setattr(Request, "form", never)
    files = [("files", ("doc.jpg", _image("JPEG", 40, 30), "image/jpeg"))]
    r = api.post("/public/requests/" + "D" * 43 + "/fill-files", files=files)
    assert r.status_code == 404 and r.json()["error"]["code"] == "REQUEST_NOT_FOUND"
    r = api.post(f"/public/requests/{token}/fill-files", files=files)
    assert r.status_code == 409 and r.json()["error"]["code"] == "REQUEST_PHOTOS_DISABLED"


def test_multipart_quebrado_no_link_vira_400(api, api2, demo_docx, fake_ai) -> None:  # type: ignore[no-untyped-def]
    """Multipart malformado (MultipartParseError, que o Starlette embrulha em 400) vira FORM_INVALID tipado."""
    _, token = _link(api, demo_docx, fields=["cpf_do_contratante"], allow_photos=True)
    r = api2.tc.post(
        f"/api/v1/public/requests/{token}/fill-files",
        content=b"--xyz\r\ncabecalho sem dois pontos\r\n\r\nx\r\n--xyz--\r\n",
        headers={"Content-Type": "multipart/form-data; boundary=xyz"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "FORM_INVALID"
    assert fake_ai == []


def test_tentativas_recusadas_tem_teto_por_link(app, api, demo_docx, fake_ai) -> None:  # type: ignore[no-untyped-def]
    """Arquivo recusado antes da IA devolve a leitura; por isso o link tem também um teto de TENTATIVAS por hora,
    contado mesmo trocando de IP: mandar imagem ruim em série não vira decodificação ilimitada na API."""
    from fastapi.testclient import TestClient

    from app.modules.requests.service import READ_TRIES_PER_HOUR_LINK, READS_PER_HOUR_IP

    out, token = _link(api, demo_docx, fields=["cpf_do_contratante"], allow_photos=True)
    bad = [("files", ("x.jpg", b"\xff\xd8\xff quebrado", "image/jpeg"))]
    codes: list[int] = []
    ip = 0
    while len(codes) < READ_TRIES_PER_HOUR_LINK:
        ip += 1
        with TestClient(app, client=(f"203.0.113.{ip}", 4000)) as tc:
            for _ in range(min(READS_PER_HOUR_IP, READ_TRIES_PER_HOUR_LINK - len(codes))):
                codes.append(tc.post(f"/api/v1/public/requests/{token}/fill-files", files=bad).status_code)
    assert set(codes) == {422} and _row(out["id"]).photo_reads == 0
    with TestClient(app, client=("203.0.113.200", 4000)) as tc:
        r = tc.post(f"/api/v1/public/requests/{token}/fill-files", files=bad)
    assert r.status_code == 429 and fake_ai == []


def test_custo_de_ia_por_link_tem_teto(api, api2, demo_docx, fake_ai) -> None:  # type: ignore[no-untyped-def]
    """Custo por link: no máximo REQUEST_PHOTO_READS leituras (padrão 3), cada uma com até 3 arquivos, todas na cota
    do espaço do profissional; esgotadas, a IA não é mais chamada."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.models import AISpend
    from app.db.session import get_factory

    _, token = _link(api, demo_docx, fields=["cpf_do_contratante"], allow_photos=True)
    files = [("files", (f"f{i}.jpg", _image("JPEG", 60, 40), "image/jpeg")) for i in range(3)]
    reads = get_settings().request_photo_reads
    codes = [api2.post(f"/public/requests/{token}/fill-files", files=files).status_code for _ in range(reads + 1)]
    assert codes == [200] * reads + [429]
    assert len(fake_ai) == reads
    with get_factory()() as db:
        spend = db.scalars(select(AISpend)).all()
    assert len(spend) == reads and all(s.purpose == "fill" and s.workspace_id is not None for s in spend)


def test_pagina_publica_so_tem_texto_e_csp_com_nonce(api, api2, demo_docx) -> None:  # type: ignore[no-untyped-def]
    """OBR-8/OBR-9: nome do espaço, documento, mensagem e rótulos voltam como texto puro (o React escapa) e só dos
    campos pedidos; nenhum componente da página usa HTML cru; a CSP de /r/* exige nonce, sem script inline, sem
    plugin e sem moldura; o endereço com o token não vaza por Referer."""
    import re
    import uuid
    from pathlib import Path

    from app.db.models import DocumentGenerator, Workspace
    from app.db.session import get_factory

    evil = '"><img src=x onerror=alert(1)><script>alert(2)</script>'
    out, token = _link(api, demo_docx, fields=["cpf_do_contratante"], message=evil)
    with get_factory()() as db:
        gen = db.get(DocumentGenerator, uuid.UUID(out["target"]["id"]))
        gen.name = evil
        db.get(Workspace, gen.workspace_id).name = evil
        db.commit()
    page = api2.get(f"/public/requests/{token}").json()
    assert page["workspace"] == page["document"] == page["message"] == evil
    assert [f["name"] for f in page["fields"]] == ["cpf_do_contratante"]

    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    page_dir = [front / "app" / "r", front / "components" / "requests", front / "components" / "form"]
    for d in page_dir:
        for f in d.rglob("*.tsx"):
            text = f.read_text(encoding="utf-8")
            assert "dangerouslySetInnerHTML" not in text and ".innerHTML" not in text, f.name
    proxy = (front / "proxy.ts").read_text(encoding="utf-8")
    assert '"/r/:path*"' in proxy
    csp = (front / "lib" / "csp.ts").read_text(encoding="utf-8")
    script_src = next(line for line in csp.splitlines() if "script-src" in line)
    assert "unsafe-inline" not in script_src and "nonce-" in script_src
    for directive in ("object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"):
        assert directive in csp
    assert re.search(r'referrer:\s*"no-referrer"', (front / "app" / "r" / "[token]" / "page.tsx").read_text())

"""Conversor de PDF isolado (D35): o serviço `pdfconv` e o cliente da API, falando HTTP de verdade.

O isolamento em si (rede interna sem saída, sem segredos, somente leitura, sem capabilities) é configuração do
contêiner (docker-compose.yml); aqui fica o contrato: o que o serviço aceita/recusa e como a API reage.
"""

from __future__ import annotations

import threading

import pytest

from app.core.config import Settings, reset_settings_cache
from app.docx_engine.pdf_import import PdfConversion, convert_pdf_remote, pdf_to_docx
from app.docx_engine.safety import DocxRejected
from app.pdfconv import server
from tests import pdf_samples
from tests.flows import upload

MB = 1024 * 1024


@pytest.fixture()
def pdfconv():  # type: ignore[no-untyped-def]
    srv = server.make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_health(pdfconv):
    import httpx

    assert httpx.get(f"{pdfconv}/health").text == "ok"


def test_typed_pdf_is_converted_by_the_service(pdfconv):
    data = pdf_samples.typed_pdf()
    conv = convert_pdf_remote(data, url=pdfconv, max_bytes=15 * MB)
    assert conv.docx[:2] == b"PK"  # .docx = zip
    assert conv.stats == pdf_to_docx(data).stats  # mesmo resultado da conversão local
    assert any("convertido de PDF" in w for w in conv.warnings)


def test_refusals_cross_the_service_with_code_and_message(pdfconv):
    with pytest.raises(DocxRejected) as exc:
        convert_pdf_remote(pdf_samples.scanned_pdf(), url=pdfconv, max_bytes=15 * MB)
    assert exc.value.code == "PDF_SCANNED" and "digitalizado" in exc.value.message
    with pytest.raises(DocxRejected) as exc:
        convert_pdf_remote(b"%PDF-1.7 lixo", url=pdfconv, max_bytes=15 * MB)
    assert exc.value.code == "NOT_A_PDF"


def test_service_limits_size_and_concurrency(pdfconv, monkeypatch: pytest.MonkeyPatch):
    data = pdf_samples.typed_pdf()
    monkeypatch.setattr(
        server, "MAX_BYTES", 100
    )  # o serviço tem o próprio limite, mesmo que a API mande mais
    with pytest.raises(DocxRejected) as exc:
        convert_pdf_remote(data, url=pdfconv, max_bytes=15 * MB)
    assert exc.value.code == "FILE_TOO_LARGE"
    monkeypatch.undo()
    busy = threading.BoundedSemaphore(1)
    busy.acquire()
    monkeypatch.setattr(
        server, "_INFLIGHT", busy
    )  # todas as vagas ocupadas → 503, a API pede para tentar de novo
    with pytest.raises(DocxRejected) as exc:
        convert_pdf_remote(data, url=pdfconv, max_bytes=15 * MB)
    assert exc.value.code == "PDF_CONVERTER_UNAVAILABLE"


def test_service_down_is_a_clear_refusal():
    with pytest.raises(DocxRejected) as exc:
        convert_pdf_remote(pdf_samples.typed_pdf(), url="http://127.0.0.1:9", max_bytes=15 * MB)
    assert exc.value.code == "PDF_CONVERTER_UNAVAILABLE"


def test_pdf_import_mode_requires_the_isolated_service_in_production():
    def mode(**kw: object) -> str:
        return Settings.model_construct(**kw).pdf_import_mode

    assert mode(app_env="production", pdf_import_enabled=False) == "off"
    assert (
        mode(app_env="production", pdf_import_enabled=True, pdf_converter_url=None) == "off"
    )  # sem isolamento
    assert (
        mode(app_env="production", pdf_import_enabled=True, pdf_converter_url="http://pdfconv:8090")
        == "service"
    )
    assert mode(app_env="development", pdf_import_enabled=True, pdf_converter_url=None) == "process"


@pytest.fixture()
def api_with_service(api, pdfconv, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PDF_CONVERTER_URL", pdfconv)
    reset_settings_cache()
    yield api
    reset_settings_cache()


def test_upload_goes_through_the_isolated_service(api_with_service, monkeypatch: pytest.MonkeyPatch):
    api = api_with_service
    local = []
    monkeypatch.setattr(
        "app.modules.templates.service.convert_pdf", lambda *a, **k: local.append(1)
    )  # o caminho local não pode ser usado quando há serviço
    api.register()
    assert api.get("/auth/me").json()["features"]["pdf_import"] is True
    gid = api.post("/generators", json={"name": "PDF isolado"}).json()["id"]
    r = upload(api, gid, pdf_samples.typed_pdf(), "contrato.pdf")
    assert r.status_code == 201, r.text
    assert r.json()["version"]["source_format"] == "pdf" and local == []


def test_converted_docx_is_validated_like_any_upload(api_with_service, monkeypatch: pytest.MonkeyPatch):
    """Se o leitor de PDF fosse comprometido, a saída dele não entra sem as checagens de um .docx enviado."""
    api = api_with_service
    monkeypatch.setattr(
        "app.modules.templates.service.convert_pdf_remote",
        lambda *a, **k: PdfConversion(docx=b"isto nao e um zip", stats={}, warnings=[]),
    )
    api.register()
    gid = api.post("/generators", json={"name": "Saída ruim"}).json()["id"]
    r = upload(api, gid, pdf_samples.typed_pdf(), "contrato.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_A_DOCX"  # recusado pela validação do .docx


def test_info_counts_pages_in_the_isolated_service(pdfconv):
    """`POST /info` (D39): a API estima o custo da leitura por IA pela contagem real de páginas, sem abrir o PDF."""
    from app.docx_engine.pdf_import import pdf_info_remote

    assert pdf_info_remote(pdf_samples.typed_pdf(), url=pdfconv) == {"pages": 2}  # o contrato de exemplo
    assert pdf_info_remote(pdf_samples.scanned_pdf(pages=3), url=pdfconv) == {"pages": 3}
    with pytest.raises(DocxRejected) as exc:
        pdf_info_remote(b"%PDF-1.4 quebrado", url=pdfconv)
    assert exc.value.code == "NOT_A_PDF"
    with pytest.raises(DocxRejected) as exc:
        pdf_info_remote(b"%PDF-1.7", url="http://127.0.0.1:9")  # fora do ar
    assert exc.value.code == "PDF_CONVERTER_UNAVAILABLE"

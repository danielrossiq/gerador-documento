"""Sugestão automática de valor com extenso: "R$ 5.000,00 (cinco mil reais)" no documento enviado vira UM campo
Valor com currency_format="words" — e a detecção é 100% local (sem rede, sem IA, sem telemetria de conteúdo)."""

from __future__ import annotations

import io
import socket

import pytest
from docx import Document

from app.modules.suggestions.rules import detect_rules
from tests.flows import docx_text, upload


def _currency(text: str):
    return [h for h in detect_rules([("b", text)]) if h.type == "currency"]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Qualquer tentativa de abrir conexão de rede falha o teste."""

    def blocked(*_a, **_k):
        raise AssertionError("tentativa de conexão de rede durante a detecção")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def test_value_followed_by_matching_words_is_one_field_in_words(no_network):
    (h,) = _currency("pelo valor de R$ 5.000,00 (cinco mil reais), pagos em 12 parcelas")
    assert h.text == "R$ 5.000,00 (cinco mil reais)"
    assert h.config == {"currency_format": "words"} and h.confidence > 0.95
    assert "não confere" not in h.reason


def test_cents_and_long_words(no_network):
    (h,) = _currency("R$ 1.234,50 (mil duzentos e trinta e quatro reais e cinquenta centavos).")
    assert h.text.endswith("cinquenta centavos)") and h.config == {"currency_format": "words"}


def test_words_that_do_not_match_the_value_are_still_captured_and_flagged(no_network):
    (h,) = _currency("R$ 5.000,00 (seis mil reais)")
    assert h.text == "R$ 5.000,00 (seis mil reais)" and h.config == {"currency_format": "words"}
    assert "não confere" in h.reason


@pytest.mark.parametrize(
    "text",
    [
        "R$ 5.000,00 (cláusula 3)",  # parênteses sem extenso
        "R$ 5.000,00 (ver anexo I)",
        "R$ 5.000,00 - cinco mil reais",  # sem parênteses: fica só o valor
    ],
)
def test_parentheses_without_words_keep_the_plain_value(text, no_network):
    (h,) = _currency(text)
    assert h.text == "R$ 5.000,00" and h.config is None


def test_mixed_values_in_one_paragraph(no_network):
    hits = _currency("multa de R$ 100,00 (cem reais) e R$ 50,00 por dia de atraso")
    assert [(h.text, h.config) for h in hits] == [
        ("R$ 100,00 (cem reais)", {"currency_format": "words"}),
        ("R$ 50,00", None),
    ]


def _docx(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_upload_accept_and_generate_with_words(api, monkeypatch: pytest.MonkeyPatch):
    """Upload → sugestão → aceitar → gerar, sem IA externa e sem rede: o extenso antigo some e o novo é gerado."""
    calls: list[str] = []

    def no_ai():
        calls.append("ai")
        return None

    monkeypatch.setattr("app.modules.suggestions.service.get_ai_provider", no_ai)
    api.register()
    gid = api.post("/generators", json={"name": "Honorários"}).json()["id"]
    content = _docx(
        [
            "CONTRATO DE HONORÁRIOS ADVOCATÍCIOS",
            "O CONTRATANTE pagará ao escritório o valor de R$ 5.000,00 (cinco mil reais), em parcela única.",
        ]
    )
    with monkeypatch.context() as m:  # a análise (regras locais) acontece no upload: nenhuma conexão de rede
        m.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede")))
        assert upload(api, gid, content).status_code in (200, 201)
    assert calls, "a análise consultou o provedor (que devolveu None = só regras locais)"

    items = api.get(f"/generators/{gid}/suggestions").json()["items"]
    (valor,) = [s for s in items if s["suggested_type"] == "currency"]
    assert valor["text"] == "R$ 5.000,00 (cinco mil reais)"

    out = api.post(f"/suggestions/{valor['id']}/accept").json()
    field = out["field"]
    assert out["applied"] == 1
    assert field["config"] == {"currency_format": "words"}
    assert field["example"] == "R$ 5.000,00"  # exemplo é só o valor; o extenso vem dele

    job = api.post(
        f"/generators/{gid}/generate", json={"values": {field["name"]: "1.234,50"}, "format": "docx"}
    ).json()
    (file,) = job["files"]
    text = docx_text(api.tc.get(api.post(f"/files/{file['id']}/link").json()["url"]).content)
    assert "R$ 1.234,50 (mil duzentos e trinta e quatro reais e cinquenta centavos)" in text
    assert "cinco mil reais" not in text and "5.000,00" not in text

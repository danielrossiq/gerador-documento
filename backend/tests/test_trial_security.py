"""Testes de regressão de segurança da sprint (teste grátis / link do cliente / assinatura).

Documentam o COMPORTAMENTO EXIGIDO pelos requisitos de docs/SEGURANCA_SPRINT.md. O que depende de código ainda não
entregue pelo engenheiro está marcado `xfail` com o requisito correspondente — quando o código chegar, o teste passa
(e o `xfail(strict=True)` acusa se alguém "consertar" sem o teste saber).

Nenhum teste fala com a rede real.
"""

from __future__ import annotations

import uuid

import pytest
from starlette.requests import Request

from app.core.deps import client_ip


def _req(headers: dict[str, str], client: tuple[str, int]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client,
        }
    )


# ---------------------------------------------------------------- OBR-0: IP real do cliente


def test_client_ip_sem_proxy_usa_o_peer() -> None:
    """Sem X-Forwarded-For, vale o endereço da conexão. Isto já funciona hoje."""
    assert client_ip(_req({}, ("203.0.113.9", 5000))) == "203.0.113.9"


def test_client_ip_ignora_xff_de_cliente_nao_confiavel() -> None:
    # Conexão direta de um IP qualquer (não é proxy nosso) mandando XFF forjado: o XFF deve ser IGNORADO.
    assert client_ip(_req({"x-forwarded-for": "1.2.3.4"}, ("203.0.113.9", 5000))) == "203.0.113.9"


def test_client_ip_atras_de_proxy_confiavel_descarta_entradas_forjadas() -> None:
    # O proxy Docker (10.0.0.5) anexou o IP real no fim; "9.9.9.9" é forjado pelo cliente e deve ser descartado.
    assert client_ip(_req({"x-forwarded-for": "9.9.9.9, 198.51.100.7"}, ("10.0.0.5", 5000))) == "198.51.100.7"


def test_xff_forjado_nao_fura_limite_de_cadastro(api) -> None:  # type: ignore[no-untyped-def]
    # Sem a correção, cada XFF diferente é um 'IP' novo e nunca estoura (PoC confirmou 12x201).
    codes = []
    for i in range(12):
        r = api.post(
            "/auth/register",
            json={
                "name": "Teste Seg",
                "email": f"seg-{uuid.uuid4().hex[:8]}@exemplo.test",
                "password": "senha-forte-123",
            },
            headers={"X-Forwarded-For": f"203.0.113.{i + 1}"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"nenhum 429 — o limite por IP foi furado pelo X-Forwarded-For: {codes}"


# ---------------------------------------------------------------- A: teste grátis (D38) — ainda não implementado


def test_teste_gratis_limita_por_ip_contando_tentativas(api) -> None:  # type: ignore[no-untyped-def]
    # Esperado: a partir do 4º teste na mesma hora pelo mesmo IP → 429, contando TENTATIVAS (inclusive falhas de IA).
    last = None
    for _ in range(6):
        last = api.post(
            "/public/trials", files={"file": ("x.docx", b"PK\x03\x04", "application/octet-stream")}
        )
    assert last is not None and last.status_code == 429


def test_budget_do_teste_nao_derruba_ia_dos_clientes(api) -> None:  # type: ignore[no-untyped-def]
    # Esperado: esgotar TRIAL_AI_DAILY_BUDGET_USD (finalidade 'trial') não reduz a disponibilidade de IA de um
    # workspace pagante. Concretizar quando a finalidade 'trial' existir no ai_budget.
    from decimal import Decimal

    from app.core.config import reset_settings_cache
    from app.modules import ai_budget

    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("AI_MONTHLY_BUDGET_USD", "1")
        mp.setenv("AI_MAX_CALL_USD", "1")
        reset_settings_cache()
        cap = Decimal("4.5")
        # o teste grátis gasta 4x o teto mensal global inteiro (dentro do teto diário dele)...
        for _ in range(10):
            ai_budget.reserve("m", "trial", Decimal("0.4"), daily_cap_usd=cap)
        # ...e quem paga continua com IA: o mensal global não conta a finalidade 'trial'
        ai_budget.reserve("m", "fill", Decimal("0.5"), workspace_id=None)
        with pytest.raises(ai_budget.BudgetExceeded) as exc:  # o teste para no teto diário dele
            ai_budget.reserve("m", "trial", Decimal("0.9"), daily_cap_usd=cap)
        assert exc.value.code == "AI_DAILY_BUDGET_EXHAUSTED"
        with pytest.raises(ai_budget.BudgetExceeded):  # e nunca sai sem teto diário
            ai_budget.reserve("m", "trial", Decimal("0.01"))
    finally:
        mp.undo()
        reset_settings_cache()


# ---------------------------------------------------------------- B: link do cliente (D39) — páginas públicas


def test_pagina_do_cliente_escapa_conteudo_do_profissional(api, api2, demo_docx) -> None:  # type: ignore[no-untyped-def]
    """OBR-8: o que o profissional (ou o visitante) escreve chega como TEXTO na API e é exibido pelo React sem HTML
    cru; as páginas públicas têm CSP com nonce. (O E2E `client-request.spec.ts` confere a mensagem escapada.)"""
    from pathlib import Path

    from tests.flows import build_generator

    api.register()
    gid = build_generator(api, demo_docx)["id"]
    evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    url = api.post(f"/generators/{gid}/client-requests", json={"message": evil}).json()["url"]
    page = api2.get("/public/requests/" + url.rsplit("/r/", 1)[1]).json()
    assert page["message"] == evil  # JSON puro: quem escapa é o React, nunca innerHTML

    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    public_files = [
        front / "app" / "r" / "[token]" / "page.tsx",
        front / "components" / "requests" / "client-form.tsx",
        front / "components" / "site" / "trial-upload.tsx",
        front / "components" / "form" / "doc-preview.tsx",
    ]
    for f in public_files:
        assert "dangerouslySetInnerHTML" not in f.read_text(encoding="utf-8"), f.name
    proxy = (front / "proxy.ts").read_text(encoding="utf-8")
    csp = (front / "lib" / "csp.ts").read_text(encoding="utf-8")
    assert '"/r/:path*"' in proxy and 'source: "/"' in proxy
    script_src = next(line for line in csp.splitlines() if "script-src" in line)
    assert "unsafe-inline" not in script_src and "nonce-" in script_src

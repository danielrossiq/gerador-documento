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


@pytest.mark.xfail(
    strict=True,
    reason="OBR-0: cliente que não é proxy confiável não pode ditar o X-Forwarded-For (hoje client_ip confia cego).",
)
def test_client_ip_ignora_xff_de_cliente_nao_confiavel() -> None:
    # Conexão direta de um IP qualquer (não é proxy nosso) mandando XFF forjado: o XFF deve ser IGNORADO.
    assert client_ip(_req({"x-forwarded-for": "1.2.3.4"}, ("203.0.113.9", 5000))) == "203.0.113.9"


@pytest.mark.xfail(
    strict=True,
    reason="OBR-0: atrás de proxy confiável, usar o 1º host à esquerda que não seja proxy confiável, não o 1º da lista.",
)
def test_client_ip_atras_de_proxy_confiavel_descarta_entradas_forjadas() -> None:
    # O proxy Docker (10.0.0.5) anexou o IP real no fim; "9.9.9.9" é forjado pelo cliente e deve ser descartado.
    assert client_ip(_req({"x-forwarded-for": "9.9.9.9, 198.51.100.7"}, ("10.0.0.5", 5000))) == "198.51.100.7"


@pytest.mark.xfail(
    strict=True,
    reason="OBR-0: com X-Forwarded-For forjado variável, o limite de cadastro por IP (10/h) ainda deve travar.",
)
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


@pytest.mark.xfail(strict=False, reason="OBR-1..5: POST /public/trials ainda não existe (claude/sprint-features).")
def test_teste_gratis_limita_por_ip_contando_tentativas(api) -> None:  # type: ignore[no-untyped-def]
    # Esperado: a partir do 4º teste na mesma hora pelo mesmo IP → 429, contando TENTATIVAS (inclusive falhas de IA).
    last = None
    for _ in range(6):
        last = api.post("/public/trials", files={"file": ("x.docx", b"PK\x03\x04", "application/octet-stream")})
    assert last is not None and last.status_code == 429


@pytest.mark.xfail(strict=False, reason="OBR-5: o budget do teste não pode consumir o teto de IA dos clientes.")
def test_budget_do_teste_nao_derruba_ia_dos_clientes() -> None:
    # Esperado: esgotar TRIAL_AI_DAILY_BUDGET_USD (finalidade 'trial') não reduz a disponibilidade de IA de um
    # workspace pagante. Concretizar quando a finalidade 'trial' existir no ai_budget.
    raise AssertionError("pendente: finalidade 'trial' isolada do AI_MONTHLY_BUDGET_USD")


# ---------------------------------------------------------------- B: link do cliente (D39) — páginas públicas


@pytest.mark.xfail(strict=False, reason="OBR-8: página pública /r/{token} ainda não existe; XSS a cobrir no front.")
def test_pagina_do_cliente_escapa_conteudo_do_profissional() -> None:
    raise AssertionError("pendente: /r/{token} deve escapar nome do espaço, mensagem e rótulos (sem HTML cru)")

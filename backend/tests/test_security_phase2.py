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

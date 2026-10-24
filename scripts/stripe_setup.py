"""Configura a Stripe para o Minuta: 2 produtos, 4 preços recorrentes (valores de plans.json) e o portal do cliente.

Idempotente: os preços são achados pelo `lookup_key` e o portal pela metadata `minuta=1`; rodar de novo não duplica.
Grava os IDs (não são segredos) no .env da raiz, que o docker compose lê. A chave secreta só é lida do arquivo.

Uso:
  python scripts/stripe_setup.py                       # modo teste: ~/.minuta/stripe-test.key
  python scripts/stripe_setup.py --key-file CAMINHO --live   # produção (chave sk_live_/rk_live_)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "backend" / "app" / "modules" / "billing" / "plans.json"
API = "https://api.stripe.com/v1"


def flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            out += flatten(v, key)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                out += flatten(item, f"{key}[{i}]") if isinstance(item, dict) else [(f"{key}[{i}]", str(item))]
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


class Stripe:
    def __init__(self, key: str) -> None:
        self.http = httpx.Client(base_url=API, auth=(key, ""), timeout=30)

    def get(self, path: str, params: dict | None = None) -> dict:
        r = self.http.get(path, params=flatten(params or {}))
        r.raise_for_status()
        return r.json()

    def post(self, path: str, data: dict) -> dict:
        r = self.http.post(path, content=urlencode(flatten(data)), headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code >= 400:
            raise SystemExit(f"Stripe recusou {path}: {r.json().get('error', {}).get('message')}")
        return r.json()


def ensure_product(s: Stripe, plan: dict) -> str:
    for p in s.get("/products", {"limit": 100, "active": True})["data"]:
        if p.get("metadata", {}).get("minuta_plan") == plan["id"]:
            return p["id"]
    return s.post("/products", {"name": f"Minuta {plan['name']}", "description": plan["tagline"], "metadata": {"minuta_plan": plan["id"]}})["id"]


def ensure_price(s: Stripe, product: str, plan: dict, cycle: str) -> str:
    lookup = f"minuta_{plan['id']}_{cycle}"
    found = s.get("/prices", {"lookup_keys": [lookup], "active": True})["data"]
    cents = round(plan["monthly"] * 100) if cycle == "mensal" else round(plan["annualMonthly"] * 12 * 100)
    if found and found[0]["unit_amount"] == cents and found[0]["currency"] == "brl":
        return found[0]["id"]
    price = s.post(
        "/prices",
        {
            "product": product,
            "currency": "brl",
            "unit_amount": cents,
            "recurring": {"interval": "month" if cycle == "mensal" else "year"},
            "lookup_key": lookup,
            "transfer_lookup_key": True,  # valor mudou em plans.json: o novo preço assume o lookup_key
            "nickname": f"{plan['name']} {cycle}",
        },
    )
    return price["id"]


def ensure_portal(s: Stripe, products: dict[str, list[str]], site: str) -> str:
    data = {
        "business_profile": {
            "headline": "Minuta: gerencie sua assinatura",
            "privacy_policy_url": f"{site}/privacidade",
            "terms_of_service_url": f"{site}/termos",
        },
        "features": {
            "customer_update": {"enabled": True, "allowed_updates": ["email", "address", "tax_id"]},
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
            "subscription_update": {
                "enabled": True,
                "default_allowed_updates": ["price"],
                "proration_behavior": "create_prorations",
                "products": [{"product": p, "prices": prices} for p, prices in products.items()],
            },
        },
        "metadata": {"minuta": "1"},
    }
    for c in s.get("/billing_portal/configurations", {"limit": 100, "active": True})["data"]:
        if c.get("metadata", {}).get("minuta") == "1":
            s.post(f"/billing_portal/configurations/{c['id']}", data)  # atualiza (ex.: preço novo)
            return c["id"]
    return s.post("/billing_portal/configurations", data)["id"]


def write_env(values: dict[str, str]) -> Path:
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    keep = [ln for ln in lines if not re.match(rf"^({'|'.join(values)})=", ln)]
    keep += [f"{k}={v}" for k, v in values.items()]
    env.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file", default=str(Path.home() / ".minuta" / "stripe-test.key"))
    ap.add_argument("--live", action="store_true", help="aceitar chave de produção")
    ap.add_argument("--site", default="https://minuta.app", help="URL pública (termos/privacidade no portal)")
    args = ap.parse_args()
    key = Path(args.key_file).read_text(encoding="utf-8").strip()
    live = key.startswith(("sk_live_", "rk_live_"))
    if live and not args.live:
        raise SystemExit("Chave de PRODUÇÃO: rode com --live se for isso mesmo.")
    s = Stripe(key)
    plans = [p for p in json.loads(PLANS.read_text(encoding="utf-8"))["plans"] if p["monthly"] > 0]
    env: dict[str, str] = {}
    portal_products: dict[str, list[str]] = {}
    for plan in plans:
        product = ensure_product(s, plan)
        for cycle in ("mensal", "anual"):
            pid = ensure_price(s, product, plan, cycle)
            env[f"STRIPE_PRICE_{plan['id'].upper()}_{cycle.upper()}"] = pid
            portal_products.setdefault(product, []).append(pid)
    env["STRIPE_PORTAL_CONFIGURATION"] = ensure_portal(s, portal_products, args.site.rstrip("/"))
    path = write_env(env)
    print(f"Modo {'PRODUÇÃO' if live else 'teste'}: IDs gravados em {path}")
    for k, v in env.items():
        print(f"  {k}={v}")


if __name__ == "__main__":
    main()

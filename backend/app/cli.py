"""Comandos administrativos: `python -m app.cli <comando>`.

seed                      cria workspace/usuário/gerador de demonstração (idempotente)
cleanup                   remove arquivos gerados expirados (agendar via cron/Kubernetes CronJob)
requeue-stuck             reenfileira jobs abandonados por um worker que caiu (o worker já faz isso sozinho)
export-workspace ID OUT   exporta os dados do workspace em JSON (LGPD: portabilidade)
purge-workspace ID --yes  apaga workspace e arquivos (LGPD: eliminação)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging


def cmd_cleanup(_: argparse.Namespace) -> int:
    """Saída != 0 quando algum arquivo expirado não pôde ser removido: o agendador (cron/CronJob) deve alertar."""
    from app.modules.generation.runner import cleanup_expired_report

    r = cleanup_expired_report()
    print(
        f"arquivos expirados removidos: {r['removidos']} · falhas: {r['falhas']} · ainda pendentes: {r['pendentes']}"
    )
    return 1 if r["falhas"] else 0


def cmd_requeue(_: argparse.Namespace) -> int:
    from app.modules.generation.runner import requeue_stuck_jobs

    n = requeue_stuck_jobs()
    print(f"jobs abandonados reenfileirados: {n}")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    from seed.seed import run_seed

    return run_seed()


def cmd_export(args: argparse.Namespace) -> int:
    from app.db import models as m
    from app.db.session import get_factory

    ws_id = uuid.UUID(args.workspace_id)

    def rows(model, **flt):  # type: ignore[no-untyped-def]
        with get_factory()() as db:
            items = db.scalars(select(model).where(model.workspace_id == ws_id)).all()
        return [
            {
                c.key: (str(getattr(i, c.key)) if getattr(i, c.key) is not None else None)
                for c in model.__table__.columns
            }
            for i in items
        ]

    data = {
        "workspace_id": args.workspace_id,
        "generators": rows(m.DocumentGenerator),
        "versions": rows(m.TemplateVersion),
        "fields": rows(m.Field),
        "jobs": rows(m.GenerationJob),
        "items": rows(m.GenerationItem),
        "files": rows(m.GeneratedFile),
        "audit_events": rows(m.AuditEvent),
        "observacao": "Valores dos itens ficam em generation_items.values; arquivos estão no storage (chaves em files.storage_key).",
    }
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"exportado para {args.out}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    from app.modules.privacy import purge_workspace

    if not args.yes:
        print("Operação irreversível. Repita com --yes para confirmar.")
        return 2
    r = purge_workspace(uuid.UUID(args.workspace_id))
    if not r.found:
        print("workspace não encontrado (talvez já eliminado)")
        return 0
    if r.pending:
        print(
            f"ELIMINAÇÃO PENDENTE: {len(r.failed_keys)} arquivo(s) não saíram do storage; os registros foram "
            f"mantidos e o acesso já está bloqueado. Rode o mesmo comando de novo.",
            file=sys.stderr,
        )
        return 1
    print(f"workspace removido; {r.removed_files} arquivo(s) apagados do storage")
    return 0


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("cleanup").set_defaults(fn=cmd_cleanup)
    sub.add_parser("requeue-stuck").set_defaults(fn=cmd_requeue)
    e = sub.add_parser("export-workspace")
    e.add_argument("workspace_id")
    e.add_argument("out")
    e.set_defaults(fn=cmd_export)
    d = sub.add_parser("purge-workspace")
    d.add_argument("workspace_id")
    d.add_argument("--yes", action="store_true")
    d.set_defaults(fn=cmd_purge)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())

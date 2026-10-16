"""Comandos administrativos: `python -m app.cli <comando>`.

seed                      cria workspace/usuário/gerador de demonstração (idempotente)
cleanup                   remove arquivos gerados expirados (agendar via cron/Kubernetes CronJob)
requeue-stuck             reenfileira jobs abandonados por um worker que caiu (o worker já faz isso sozinho)
export-workspace ID OUT [--files DIR]  exporta o workspace em JSON (+ arquivos) — LGPD: portabilidade
purge-workspace ID --yes  apaga workspace, arquivos e contas sem outro workspace (LGPD: eliminação)
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging


def cmd_cleanup(_: argparse.Namespace) -> int:
    """Remove todos os expirados (em lotes). Saída != 0 se algum não saiu do storage ou ainda há pendentes:
    o agendador (cron/CronJob) deve alertar."""
    from app.modules.generation.runner import cleanup_expired_report

    r = cleanup_expired_report()
    print(
        f"arquivos expirados removidos: {r['removidos']} · falhas: {r['falhas']} · ainda pendentes: {r['pendentes']}"
    )
    return 1 if r["falhas"] or r["pendentes"] else 0


def cmd_requeue(_: argparse.Namespace) -> int:
    from app.modules.generation.runner import requeue_stuck_jobs

    n = requeue_stuck_jobs()
    print(f"jobs abandonados reenfileirados: {n}")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    from seed.seed import run_seed

    return run_seed()


def cmd_export(args: argparse.Namespace) -> int:
    """JSON com todas as tabelas do workspace, sem segredos; --files DIR copia também os arquivos do storage."""
    from app.modules.privacy import export_workspace

    try:
        summary = export_workspace(
            uuid.UUID(args.workspace_id), Path(args.out), Path(args.files) if args.files else None
        )
    except LookupError:
        print("workspace não encontrado", file=sys.stderr)
        return 1
    total = sum(summary["tabelas"].values())
    print(f"exportado para {args.out}: {total} registro(s) em {len(summary['tabelas'])} tabela(s)", end="")
    if args.files:
        print(f"; {summary['arquivos']} arquivo(s) em {args.files}, {summary['falhas_arquivo']} falha(s)")
    else:
        print(" (sem os arquivos: use --files DIR para incluí-los)")
    return 1 if summary["falhas_arquivo"] else 0


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
    print(
        f"workspace removido; {r.removed_files} arquivo(s) apagados do storage; "
        f"{r.users_deleted} conta(s) sem outro workspace removida(s)"
    )
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
    e.add_argument("--files", help="pasta para copiar os arquivos do storage (modelos e documentos gerados)")
    e.set_defaults(fn=cmd_export)
    d = sub.add_parser("purge-workspace")
    d.add_argument("workspace_id")
    d.add_argument("--yes", action="store_true")
    d.set_defaults(fn=cmd_purge)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())

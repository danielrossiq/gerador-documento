"""Comandos administrativos: `python -m app.cli <comando>`.

seed                      cria workspace/usuário/gerador de demonstração (idempotente)
cleanup                   remove arquivos gerados expirados (agendar via cron/Kubernetes CronJob)
metrics-rollup            agregados diários de ativação (opt-in; D32)
metrics-report            lista os agregados de ativação
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
    from app.db.session import get_factory
    from app.modules.generation.runner import cleanup_expired_report
    from app.modules.metrics.activation import purge_expired
    from app.modules.trials.service import purge_expired_trials

    r = cleanup_expired_report()
    trials = purge_expired_trials()  # testes grátis da landing vencidos (D38)
    print(f"testes grátis vencidos removidos: {trials['removidos']} · falhas: {trials['falhas']}")
    with get_factory()() as db:  # agregados de ativação com mais de 30 dias (D32)
        expired_metrics = purge_expired(db)
        db.commit()
    print(f"agregados de ativação expirados removidos: {expired_metrics}")
    print(
        f"arquivos expirados removidos: {r['removidos']} · falhas: {r['falhas']} · ainda pendentes: {r['pendentes']}"
    )
    return 1 if r["falhas"] or r["pendentes"] or trials["falhas"] else 0


def cmd_metrics_rollup(_: argparse.Namespace) -> int:
    """Agregados diários de ativação (opt-in, D32). Agendar 1x/dia; também aplica a retenção de 30 dias."""
    from app.modules.metrics.activation import rollup

    r = rollup()
    if not r.enabled:
        print(
            f"métricas de ativação desligadas (ACTIVATION_METRICS_ENABLED); expiradas removidas: {r.rows_expired}"
        )
        return 0
    print(
        f"agregados gravados: {r.rows_written} ({r.rows_suppressed} suprimidos por < 5); expirados: {r.rows_expired}"
    )
    return 0


def cmd_metrics_report(_: argparse.Namespace) -> int:
    """Lista os agregados (só período × métrica × contagem; '<5' quando suprimido)."""
    from app.modules.metrics.activation import report

    rows = report()
    if not rows:
        print("sem agregados (métricas desligadas ou ainda não calculadas)")
    for r in rows:
        value = "<5" if r.suppressed else str(r.value)
        print(f"{r.period_kind} | {r.period_start.isoformat()} | {r.metric} | {value}")
    return 0


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


def cmd_ai_eval(args: argparse.Namespace) -> int:
    """Conjunto ouro (app/eval): `baseline` = regras e heurísticas locais, sem rede; `models` = modelos da OpenRouter
    lado a lado (usa a chave e gasta, com teto em --budget)."""
    from app.eval import baseline
    from app.eval.gold import validate

    if problems := validate():
        print("conjunto ouro inconsistente:", *problems, sep="\n  ")
        return 1
    if args.mode == "models":
        from app.eval import ai_models

        models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
        if not models:
            print("informe --models modelo1,modelo2")
            return 1
        return ai_models.main(models, args.budget, args.md, args.json)
    return baseline.main(args.json, args.md)


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("cleanup").set_defaults(fn=cmd_cleanup)
    sub.add_parser("requeue-stuck").set_defaults(fn=cmd_requeue)
    sub.add_parser("metrics-rollup").set_defaults(fn=cmd_metrics_rollup)
    sub.add_parser("metrics-report").set_defaults(fn=cmd_metrics_report)
    e = sub.add_parser("export-workspace")
    e.add_argument("workspace_id")
    e.add_argument("out")
    e.add_argument("--files", help="pasta para copiar os arquivos do storage (modelos e documentos gerados)")
    e.set_defaults(fn=cmd_export)
    d = sub.add_parser("purge-workspace")
    d.add_argument("workspace_id")
    d.add_argument("--yes", action="store_true")
    d.set_defaults(fn=cmd_purge)
    a = sub.add_parser("ai-eval", help="avaliação da IA integrada no conjunto ouro fictício (sem rede)")
    a.add_argument("mode", choices=["baseline", "models"])
    a.add_argument("--models", help="modelos da OpenRouter separados por vírgula (modo models; usa a chave e gasta)")
    a.add_argument("--budget", type=float, default=1.5, help="teto de gasto da avaliação em US$ (modo models)")
    a.add_argument("--json", type=Path, help="grava o resultado completo em JSON")
    a.add_argument("--md", type=Path, help="grava o relatório em Markdown")
    a.set_defaults(fn=cmd_ai_eval)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())

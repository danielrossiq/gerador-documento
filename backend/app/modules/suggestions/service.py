"""Análise de modelo (regras determinísticas + IA/heurísticas) e revisão de sugestões.

A IA só é chamada na análise/reanálise, nunca na geração. O resultado fica em `ai_analysis_runs` associado ao
hash do que foi analisado (arquivo + texto); se o hash não mudou, a análise é reaproveitada sem nova chamada.
O usuário sempre confirma: aceitar uma sugestão cria o campo e aplica no documento; nada muda sozinho.
"""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from collections import Counter
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.ai import PROMPT_VERSION, get_ai_provider
from app.adapters.ai.base import AISuggestionRequest, AIUnavailable, BlockText
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    AIAnalysisRun,
    DocumentGenerator,
    Field,
    FieldOption,
    FieldSuggestion,
    TemplateBlock,
    TemplateFile,
    TemplateVersion,
)
from app.db.session import get_factory
from app.docx_engine.inline import inline_text
from app.docx_engine.nodes import RangeError, iter_field_spans, replace_range_with_field
from app.modules.audit import service as audit
from app.modules.fields import service as fields_service
from app.modules.fields.types import unique_name
from app.modules.suggestions.rules import (
    RULES_VERSION,
    Hit,
    adopt_semantic_names,
    describe_location,
    detect_rules,
    infer_config,
    resolve_overlaps,
)
from app.modules.templates import core

log = get_logger(__name__)


# ------------------------------------------------------------------ análise


def run_analysis_job(version_id: str, force: bool = False) -> None:
    """Ponto de entrada da fila (idempotente)."""
    with get_factory()() as db:
        version = db.get(TemplateVersion, uuid.UUID(version_id))
        if version is None:
            return
        gen = db.get(DocumentGenerator, version.generator_id)
        if gen is None or gen.current_version_id != version.id:
            return  # um novo arquivo substituiu esta versão antes da análise terminar
        try:
            analyze_version(db, version, force=force)
        except Exception:
            db.rollback()
            version = db.get(TemplateVersion, uuid.UUID(version_id))
            if version:
                version.analysis_status = "failed"
                version.analysis_error = (
                    "Falha inesperada na análise. Você ainda pode criar campos manualmente."
                )
                db.commit()
            log.exception("analise_falhou", extra={"version_id": version_id})


def _readable_blocks(db: Session, version: TemplateVersion) -> list[TemplateBlock]:
    blocks = core.load_blocks(db, version.id)
    return [
        b
        for b in core.ordered_blocks(blocks, core.part_order_of(version, blocks))
        if b.kind == "paragraph" and not (b.attrs or {}).get("hidden") and b.text.strip()
    ]


def analyze_version(db: Session, version: TemplateVersion, *, force: bool) -> AIAnalysisRun:
    settings = get_settings()
    version.analysis_status = "running"
    version.analysis_error = None
    db.commit()

    blocks = _readable_blocks(db, version)
    by_key = {b.key: b for b in blocks}
    provider = get_ai_provider()
    provider_name = provider.name if provider else "none"
    model = getattr(provider, "model", None) if provider else None
    src = db.get(TemplateFile, version.source_file_id) if version.source_file_id else None
    text_hash = hashlib.sha256("\n".join(f"{b.key}\t{b.text}" for b in blocks).encode()).hexdigest()
    analysis_hash = hashlib.sha256(f"{src.sha256 if src else ''}|{text_hash}".encode()).hexdigest()
    prompt_version = f"{PROMPT_VERSION}-{RULES_VERSION}"

    cached = None
    if not force:
        cached = db.scalar(
            select(AIAnalysisRun)
            .where(
                AIAnalysisRun.workspace_id == version.workspace_id,
                AIAnalysisRun.file_sha256 == analysis_hash,
                AIAnalysisRun.provider == provider_name,
                AIAnalysisRun.prompt_version == prompt_version,
                AIAnalysisRun.status == "succeeded",
                AIAnalysisRun.result.is_not(None),
            )
            .order_by(AIAnalysisRun.created_at.desc())
            .limit(1)
        )
    run = AIAnalysisRun(
        workspace_id=version.workspace_id,
        generator_id=version.generator_id,
        version_id=version.id,
        file_sha256=analysis_hash,
        provider=provider_name,
        model=model,
        prompt_version=prompt_version,
    )
    db.add(run)
    db.flush()

    if cached is not None:
        run.status, run.result, run.reused_from_id = "succeeded", cached.result, cached.id
        run.finished_at = utcnow()
        run.duration_ms = 0
        result = cached.result
        log.info("analise_reutilizada", extra={"version_id": str(version.id)})
    else:
        result = {"hits": [], "warnings": []}
        rule_hits = detect_rules([(b.key, b.text) for b in blocks])
        hits: list[Hit] = list(rule_hits)
        if provider is not None:
            request = AISuggestionRequest(
                [BlockText(b.key, b.text, describe_location(b.key)) for b in blocks],
                max_chars=settings.ai_max_chars,
            )
            def add(res, source: str) -> None:  # type: ignore[no-untyped-def]
                for raw in res.suggestions:
                    blk = by_key.get(raw.block)
                    if blk is None:
                        continue
                    for m in re.finditer(re.escape(raw.text), blk.text):
                        hits.append(
                            Hit(blk.key, m.start(), m.end(), raw.text, raw.name, raw.label, raw.type, raw.confidence, source, raw.reason or "", infer_config(raw.type, raw.text))
                        )

            try:
                res, provider = _suggest_within_budget(db, provider, request, version.workspace_id, result["warnings"])
                run.tokens_in, run.tokens_out = res.tokens_in, res.tokens_out
                run.chars_sent, run.duration_ms = res.chars_sent, res.duration_ms
                result["warnings"].extend(res.warnings)
                add(res, "ai" if provider.name != "local" else "local")
            except AIUnavailable as exc:
                from app.adapters.ai import LocalHeuristicProvider

                run.error_code = exc.code
                add(LocalHeuristicProvider().suggest(request), "local")
                result["warnings"].append(
                    f"IA externa indisponível ({exc.code}). Usamos só as regras e heurísticas locais."
                )
                version.analysis_error = result["warnings"][-1]
        run.result = {"hits": [asdict(h) for h in hits], "warnings": result["warnings"]}
        run.status = "succeeded"
        run.finished_at = utcnow()
        result = run.result

    materialize(db, version, [Hit(**h) for h in result["hits"]], blocks)
    version.analysis_status = "done"
    db.commit()
    return run


def _suggest_within_budget(db: Session, provider, request: AISuggestionRequest, workspace_id, warnings: list[str]):  # type: ignore[no-untyped-def]
    """Provedor pago (OpenRouter): reserva o custo máximo no teto e na cota do workspace antes de chamar e acerta
    com o custo real depois. Sem orçamento/cota ou com a IA fora do ar, a análise segue com as heurísticas locais
    (e um aviso), para a pessoa nunca ficar sem sugestão."""
    from app.adapters.ai import LocalHeuristicProvider
    from app.adapters.ai.openrouter import FIELDS_SYSTEM, build_blocks_prompt, max_output_tokens
    from app.core.deps import workspace_limit
    from app.db.models import Workspace
    from app.modules import ai_budget
    from app.modules.assist import ai as assist_ai

    if provider.name != "openrouter":
        return provider.suggest(request), provider
    prompt, chars, _ = build_blocks_prompt(request)
    ws = db.get(Workspace, workspace_id)
    quota = workspace_limit(db, ws, "max_ai_actions_per_month") if ws else None
    db.commit()  # a reserva usa transação própria (vale mesmo se a análise cair): libera a desta sessão antes
    try:
        spend_id = ai_budget.reserve(
            provider.model,
            "analysis",
            assist_ai.worst_cost(provider.model, len(FIELDS_SYSTEM) + len(prompt), max_output_tokens(chars)),
            workspace_id=workspace_id,
            quota=quota,
        )
    except ai_budget.BudgetExceeded as exc:
        warnings.append(f"{exc} Usamos as sugestões automáticas locais desta vez.")
        local = LocalHeuristicProvider()
        return local.suggest(request), local
    try:
        res = provider.suggest(request)
    except AIUnavailable:
        ai_budget.fail(spend_id)
        raise
    ai_budget.settle(spend_id, provider.last_cost_usd, res.tokens_in, res.tokens_out)
    return res, provider


def _number_duplicate_hits(hits: list[Hit]) -> list[Hit]:
    """Quando o mesmo campo-base (ex.: "cnpj") aparece com mais de um VALOR distinto no documento, numera
    nome/rótulo em ordem de aparição: "CNPJ 1", "CNPJ 2"... Ocorrências repetidas do MESMO valor continuam
    um único campo (não numeradas) — o que distingue é o valor, não a posição. `hits` já vem ordenado por
    (block_key, start) — mesma ordem que `resolve_overlaps` devolve."""
    first_hit: dict[tuple[str, str], Hit] = {}
    order: list[tuple[str, str]] = []
    for h in hits:
        key = (h.name, h.text)
        if key not in first_hit:
            first_hit[key] = h
            order.append(key)
    counts = Counter(k[0] for k in order)
    if not any(c > 1 for c in counts.values()):
        return hits
    running: dict[str, int] = {}
    renamed: dict[tuple[str, str], tuple[str, str]] = {}
    for key in order:
        base_name, _text = key
        if counts[base_name] <= 1:
            continue
        running[base_name] = running.get(base_name, 0) + 1
        idx = running[base_name]
        rep = first_hit[key]
        renamed[key] = (f"{base_name}_{idx}", f"{rep.label} {idx}")
    for h in hits:
        new = renamed.get((h.name, h.text))
        if new:
            h.name, h.label = new
    return hits


def materialize(db: Session, version: TemplateVersion, hits: list[Hit], blocks: list[TemplateBlock]) -> int:
    db.execute(
        delete(FieldSuggestion).where(
            FieldSuggestion.version_id == version.id, FieldSuggestion.status == "pending"
        )
    )
    ignored = {
        (s.block_key, s.start_offset, s.end_offset, s.text)
        for s in db.scalars(
            select(FieldSuggestion).where(
                FieldSuggestion.version_id == version.id, FieldSuggestion.status == "ignored"
            )
        )
    }
    covered = {
        b.key: [(s, e) for s, e, _ in iter_field_spans(b.content)]
        for b in blocks
        if isinstance(b.content, list)
    }
    text_of = {b.key: b.text for b in blocks}
    latest_run = db.scalar(
        select(AIAnalysisRun.id)
        .where(AIAnalysisRun.version_id == version.id)
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    )
    surviving = [
        h
        for h in adopt_semantic_names(resolve_overlaps(hits), hits)
        if (h.block_key, h.start, h.end, h.text) not in ignored
        and not any(s < h.end and h.start < e for s, e in covered.get(h.block_key, []))
    ]
    n = 0
    for h in _number_duplicate_hits(surviving):
        text = text_of.get(h.block_key, "")
        db.add(
            FieldSuggestion(
                workspace_id=version.workspace_id,
                version_id=version.id,
                analysis_run_id=latest_run,
                block_key=h.block_key,
                start_offset=h.start,
                end_offset=h.end,
                text=h.text,
                context_before=text[max(0, h.start - 40) : h.start],
                context_after=text[h.end : h.end + 40],
                suggested_name=h.name[:64],
                suggested_label=h.label[:200],
                suggested_type=h.type,
                suggested_config=h.config,
                confidence=h.confidence,
                source=h.source,
                reason=(h.reason or "")[:300],
                location=describe_location(h.block_key),
                status="pending",
            )
        )
        n += 1
    db.flush()
    return n


# ------------------------------------------------------------------ leitura


def _version_for_review(ctx: Ctx, generator_id: uuid.UUID) -> TemplateVersion:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    return core.current_version(ctx.db, gen)


def provider_label(provider: str, model: str | None) -> str:
    if provider == "local":
        return "Sugestões locais (IA externa não configurada)"
    if provider == "anthropic":
        return f"IA externa · {model}" if model else "IA externa"
    if provider == "openrouter":
        return "Campos encontrados pela IA"
    return "Somente regras determinísticas"


def _locate(block: Any, s: FieldSuggestion) -> tuple[int, int] | None:
    """Onde o trecho sugerido está hoje no bloco (o documento pode ter mudado desde a análise), ou None."""
    text = block.text or ""
    start, end = s.start_offset, s.end_offset
    if text[start:end] == s.text:
        return start, end
    found = next(
        (
            m.start()
            for m in re.finditer(re.escape(s.text), text)
            if text[max(0, m.start() - 20) : m.start()].endswith(s.context_before[-20:])
        ),
        None,
    )
    return None if found is None else (found, found + len(s.text))


def _still_applicable(block: Any, s: FieldSuggestion) -> bool:
    """A sugestão ainda pode virar campo? Falso se o trecho sumiu ou já virou campo (ex.: marcado à mão)."""
    if block is None or block.kind != "paragraph":
        return False
    pos = _locate(block, s)
    if pos is None:
        return False
    try:
        replace_range_with_field(copy.deepcopy(block.content), pos[0], pos[1], "verificacao")
    except RangeError:
        return False
    return True


def list_suggestions(ctx: Ctx, generator_id: uuid.UUID, status: str = "pending") -> dict[str, Any]:
    db = ctx.db
    version = _version_for_review(ctx, generator_id)
    rows = list(
        db.scalars(
            select(FieldSuggestion).where(
                FieldSuggestion.version_id == version.id, FieldSuggestion.status == status
            )
        )
    )
    blocks = core.ordered_blocks(core.load_blocks(db, version.id), core.part_order_of(version, []))
    order = {b.key: i for i, b in enumerate(blocks)}
    if status == "pending":
        # não oferecer o que não dá mais para aceitar (trecho apagado ou já transformado em campo à mão):
        # na interface isso aparecia como sugestão pendente e o "Aceitar" terminava em erro
        by_key = {b.key: b for b in blocks}
        rows = [r for r in rows if _still_applicable(by_key.get(r.block_key), r)]
    rows.sort(key=lambda s: (order.get(s.block_key, 10**6), s.start_offset))
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for s in rows:
        g = groups.setdefault(
            (s.suggested_name, s.text),
            {
                "id": str(s.id),
                "text": s.text,
                "suggested_name": s.suggested_name,
                "suggested_label": s.suggested_label,
                "suggested_type": s.suggested_type,
                "confidence": s.confidence,
                "source": s.source,
                "reason": s.reason,
                "occurrences": [],
            },
        )
        g["confidence"] = max(g["confidence"], s.confidence)
        g["occurrences"].append(
            {
                "id": str(s.id),
                "block_key": s.block_key,
                "location": s.location,
                "start": s.start_offset,
                "end": s.end_offset,
                "context_before": s.context_before[-30:],
                "context_after": s.context_after[:30],
            }
        )
    run = db.scalar(
        select(AIAnalysisRun)
        .where(AIAnalysisRun.version_id == version.id)
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    )
    items = sorted(groups.values(), key=lambda g: -g["confidence"])
    for g in items:
        g["count"] = len(g["occurrences"])
    return {
        "items": items,
        "analysis": {
            "status": version.analysis_status,
            "error": version.analysis_error,
            "provider": run.provider if run else None,
            "model": run.model if run else None,
            "provider_label": provider_label(run.provider, run.model) if run else None,
            "reused": bool(run and run.reused_from_id),
            "tokens_in": run.tokens_in if run else None,
            "tokens_out": run.tokens_out if run else None,
        },
    }


def request_analysis(ctx: Ctx, generator_id: uuid.UUID, force: bool) -> dict[str, Any]:
    from app.adapters.queue import enqueue

    version = core.current_version(ctx.db, core.get_generator(ctx.db, ctx.workspace_id, generator_id))
    version.analysis_status = "pending"
    audit.record(
        ctx.db,
        "template.reanalyze",
        ctx=ctx,
        entity_type="generator",
        entity_id=version.generator_id,
        meta={"force": force},
    )
    ctx.db.commit()
    try:
        enqueue("analysis", version_id=str(version.id), force=force)
    except Exception:
        log.exception("fila_indisponivel_para_reanalise")
        version.analysis_status = "failed"
        version.analysis_error = "A fila de processamento está indisponível. Tente novamente em instantes."
        ctx.db.commit()
        return {"status": "failed"}
    return {"status": "pending"}


# ------------------------------------------------------------------ revisão


class AcceptIn(BaseModel):
    name: str | None = PField(default=None, max_length=64)
    label: str | None = PField(default=None, max_length=200)
    type: str | None = None
    apply_to_all: bool = True


def _pending_group(db: Session, sug: FieldSuggestion, apply_to_all: bool) -> list[FieldSuggestion]:
    if not apply_to_all:
        return [sug]
    return list(
        db.scalars(
            select(FieldSuggestion).where(
                FieldSuggestion.version_id == sug.version_id,
                FieldSuggestion.status == "pending",
                FieldSuggestion.suggested_name == sug.suggested_name,
                FieldSuggestion.text == sug.text,
            )
        )
    )


def _get_pending(ctx: Ctx, suggestion_id: uuid.UUID) -> tuple[FieldSuggestion, TemplateVersion]:
    sug = ctx.db.scalar(
        select(FieldSuggestion).where(
            FieldSuggestion.id == suggestion_id, FieldSuggestion.workspace_id == ctx.workspace_id
        )
    )
    if sug is None:
        raise NotFound("Sugestão")
    version = core.get_version(ctx.db, ctx.workspace_id, sug.version_id)
    gen = core.get_generator(ctx.db, ctx.workspace_id, version.generator_id)
    if gen.current_version_id != version.id:
        raise Conflict(
            "Esta sugestão pertence a uma versão anterior do documento.", code="VERSION_NOT_CURRENT"
        )
    if sug.status != "pending":
        raise Conflict("Esta sugestão já foi tratada.", code="SUGGESTION_HANDLED")
    return sug, version


def accept(ctx: Ctx, suggestion_id: uuid.UUID, body: AcceptIn) -> dict[str, Any]:
    db = ctx.db
    sug, version = _get_pending(ctx, suggestion_id)
    gen = core.get_generator(db, ctx.workspace_id, version.generator_id)
    group = _pending_group(db, sug, body.apply_to_all)
    ftype = body.type or sug.suggested_type
    existing = set(db.scalars(select(Field.name).where(Field.version_id == version.id)))
    name = body.name.strip() if body.name else unique_name(sug.suggested_name, existing)
    cfg = sug.suggested_config if ftype == sug.suggested_type else None
    # algumas regras (ex.: mês) já sugerem a lista de opções inteira em vez de só o valor encontrado no
    # texto — "options" nunca deve vazar pro `config` do campo (é só metadado da sugestão, não parâmetro do tipo).
    preset_options = (cfg or {}).get("options") if ftype == "select" else None
    if preset_options:
        options = [fields_service.OptionIn(**o) for o in preset_options]
        cfg = {k: v for k, v in cfg.items() if k != "options"} or None
    else:
        options = [fields_service.OptionIn(label=sug.text)] if ftype == "select" else None
    payload = fields_service.FieldIn(
        label=(body.label or sug.suggested_label).strip(),
        name=name,
        type=ftype,
        config=cfg,
        options=options,
        default_value=None,
        # "R$ 5.000,00 (cinco mil reais)": o exemplo é só o valor (o extenso é gerado a partir dele)
        example=(sug.text.split(" (", 1)[0] if ftype == "currency" else sug.text)[:300],
    )
    field = fields_service.create_field(ctx, gen.id, payload, commit=False)
    blocks = {b.key: b for b in core.load_blocks(db, version.id)}
    applied = 0
    for s in group:
        b = blocks.get(s.block_key)
        if b is None or b.kind != "paragraph":
            s.status = "ignored"
            continue
        pos = _locate(b, s)  # documento mudou: tenta reencontrar pelo contexto
        if pos is None:
            s.status = "ignored"
            continue
        start, end = pos
        try:
            b.content, _ = replace_range_with_field(b.content, start, end, str(field.id))
        except RangeError:
            s.status = "ignored"
            continue
        b.text = inline_text(b.content)
        s.status, s.field_id = "accepted", field.id
        applied += 1
    if applied == 0:
        # nenhuma ocorrência ainda existe (o trecho virou campo à mão ou foi apagado): não deixa um campo
        # "fantasma" no formulário — descarta o campo e registra a sugestão como tratada
        db.execute(delete(FieldOption).where(FieldOption.field_id == field.id))
        db.delete(field)
        db.commit()
        raise Conflict(
            "Este trecho não existe mais no documento (talvez já tenha virado campo).",
            code="SUGGESTION_STALE",
        )
    db.flush()
    core.recompute_occurrences(db, version)
    core.touch(version, gen, content=True)
    audit.record(
        db,
        "suggestion.accept",
        ctx=ctx,
        entity_type="field",
        entity_id=field.id,
        meta={"applied": applied, "source": sug.source},
    )
    db.commit()
    counts = core.occurrence_counts(db, version.id)
    opts = fields_service.options_by_field(db, [field.id])[field.id]
    return {
        "field": fields_service.field_out(field, opts, counts.get(str(field.id), 0)),
        "applied": applied,
        "revision": version.revision,
    }


def ignore(ctx: Ctx, suggestion_id: uuid.UUID, apply_to_all: bool = True) -> int:
    sug, _ = _get_pending(ctx, suggestion_id)
    group = _pending_group(ctx.db, sug, apply_to_all)
    for s in group:
        s.status = "ignored"
    audit.record(
        ctx.db,
        "suggestion.ignore",
        ctx=ctx,
        entity_type="generator",
        entity_id=None,
        meta={"count": len(group)},
    )
    ctx.db.commit()
    return len(group)


def accept_all(ctx: Ctx, generator_id: uuid.UUID, min_confidence: float) -> dict[str, Any]:
    data = list_suggestions(ctx, generator_id, "pending")
    accepted = 0
    for g in data["items"]:
        if g["confidence"] >= min_confidence:
            try:
                accept(ctx, uuid.UUID(g["id"]), AcceptIn(apply_to_all=True))
                accepted += 1
            except Conflict:
                continue
    version = _version_for_review(ctx, generator_id)
    return {"accepted_groups": accepted, "revision": version.revision}

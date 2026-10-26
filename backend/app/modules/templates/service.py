"""Templates: upload, versões e o documento do editor (leitura/gravação reconciliada)."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.queue import enqueue
from app.adapters.storage import get_storage
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound, ServiceUnavailable, TransientError, ValidationFailed
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    DocumentGenerator,
    Field,
    FieldOccurrence,
    FieldOption,
    FieldSuggestion,
    TemplateBlock,
    TemplateFile,
    TemplateVersion,
    User,
)
from app.docx_engine.compile import BlockSpec, CompileResult, compile_docx
from app.docx_engine.editor_doc import BlockIn, DocStructureError, PartLike, blocks_to_doc, walk_doc
from app.docx_engine.inline import inline_text, normalize_nodes
from app.docx_engine.nodes import RangeError, replace_range_with_field
from app.docx_engine.parse import parse_docx
from app.docx_engine.pdf_import import PdfConversion, convert_pdf, convert_pdf_remote, looks_like_pdf
from app.docx_engine.safety import DocxRejected, validate_docx
from app.modules.audit import service as audit
from app.modules.fields import service as fields_service
from app.modules.generators import service as generators_service
from app.modules.templates import core

log = get_logger(__name__)
ATTRS_DISPLAY = ("style", "heading", "align", "list", "level")


# ------------------------------------------------------------------ upload


def upload_template(ctx: Ctx, generator_id: uuid.UUID, filename: str, data: bytes) -> TemplateVersion:
    """Recebe o documento-base: .docx direto, ou PDF digitado convertido em .docx (ver docx_engine.pdf_import).

    Do PDF guardamos só o .docx convertido — é ele que o editor edita e o gerador preenche —, mas com o nome
    do arquivo enviado, para a interface mostrar ao usuário o arquivo que ele reconhece.
    """
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    max_bytes = ctx.limit("max_upload_mb") * 1024 * 1024
    is_pdf = (filename or "").lower().endswith(".pdf") or looks_like_pdf(data)
    conversion: PdfConversion | None = None
    try:
        settings = get_settings()
        if is_pdf and settings.pdf_import_mode == "off":
            raise DocxRejected(
                "PDF_IMPORT_DISABLED",
                "O envio de PDF está desativado por enquanto. Envie o documento em Word (.docx).",
            )
        if is_pdf:
            if settings.pdf_import_mode == "service":
                conversion = convert_pdf_remote(data, url=settings.pdf_converter_url or "", max_bytes=max_bytes)
            else:
                conversion = convert_pdf(data, max_bytes=max_bytes)
            data = conversion.docx
            # o .docx convertido vem de um leitor de PDF exposto a arquivo de fora: passa pelas mesmas checagens de
            # qualquer .docx enviado (imagens podem deixá-lo maior que o PDF; daí a folga no tamanho)
            validate_docx(data, filename="convertido.docx", max_bytes=max(4 * max_bytes, 64 * 1024 * 1024))
        else:
            validate_docx(data, filename=filename or "", max_bytes=max_bytes)
    except DocxRejected as exc:
        audit.record(
            db,
            "template.upload_rejected",
            ctx=ctx,
            entity_type="generator",
            entity_id=gen.id,
            meta={"code": exc.code, "format": "pdf" if is_pdf else "docx"},
        )
        db.commit()
        raise ValidationFailed(exc.message, code=exc.code) from exc
    try:
        parsed = parse_docx(data)
    except (etree.XMLSyntaxError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise ValidationFailed(
            "Não foi possível ler o conteúdo do documento. Salve-o novamente no Word como .docx e tente de novo.",
            code="DOCX_PARSE_FAILED",
        ) from exc
    if not any(b.kind == "paragraph" for b in parsed.blocks):
        raise ValidationFailed("O documento não tem texto para transformar em modelo.", code="EMPTY_DOCUMENT")
    return create_version(
        ctx,
        gen,
        filename=filename,
        data=data,
        parsed=parsed,
        warnings=[*(conversion.warnings if conversion else []), *parsed.warnings],
        source_format="pdf" if conversion else "docx",
        pdf_stats=conversion.stats if conversion else None,
    )


def create_version(
    ctx: Ctx,
    gen: DocumentGenerator,
    *,
    filename: str,
    data: bytes,
    parsed: Any,
    warnings: list[str],
    source_format: str,
    pdf_stats: dict[str, int] | None = None,
    analyze: bool = True,
) -> TemplateVersion:
    """Grava um .docx JÁ VALIDADO e lido como a nova versão atual do modelo. `analyze=False`: quem chama cria as
    sugestões (o teste grátis da landing já analisou o documento, D38) e a análise não roda de novo."""
    db = ctx.db
    prev = core.current_version_or_none(db, gen)
    src = core.store_file(
        db,
        workspace_id=ctx.workspace_id,
        generator_id=gen.id,
        role="source",
        data=data,
        filename=filename,
        user_id=ctx.user.id,
    )
    version = TemplateVersion(
        workspace_id=ctx.workspace_id,
        generator_id=gen.id,
        version_number=core.next_version_number(db, gen.id),
        source_file_id=src.id,
        analysis_status="pending",
        created_by=ctx.user.id,
        based_on_version_id=prev.id if prev else None,
        meta={
            "stats": parsed.stats,
            "warnings": warnings,
            "parts": [
                {"name": p.name, "kind": p.kind, "label": p.label, "hidden": p.hidden} for p in parsed.parts
            ],
            "source_format": source_format,
            **({"pdf": pdf_stats} if pdf_stats is not None else {}),
        },
    )
    db.add(version)
    db.flush()
    for b in parsed.blocks:
        db.add(
            TemplateBlock(
                workspace_id=ctx.workspace_id,
                version_id=version.id,
                key=b.key,
                part=b.part,
                container_key=b.container_key,
                ordinal=b.ordinal,
                kind=b.kind,
                origin="original",
                content=b.content,
                attrs=b.attrs or None,
                text=b.text,
                source_text=b.text,
            )
        )
    db.flush()
    if prev is not None:
        carry_over_fields(db, ctx, prev, version)
    core.recompute_occurrences(db, version)
    gen.current_version_id = version.id
    gen.updated_at = utcnow()
    audit.record(
        db,
        "template.upload",
        ctx=ctx,
        entity_type="generator",
        entity_id=gen.id,
        meta={
            "version": version.version_number,
            "size": len(data),
            "sha256": src.sha256,
            "format": source_format,
        },
    )
    db.commit()
    if not analyze:
        return version
    try:
        enqueue("analysis", version_id=str(version.id))
    except Exception:
        log.exception("fila_indisponivel_para_analise", extra={"version_id": str(version.id)})
        version.analysis_status = "failed"
        version.analysis_error = (
            "Não foi possível iniciar a análise agora. Você ainda pode criar os campos manualmente."
        )
        db.commit()
    return version


def carry_over_fields(db: Session, ctx: Ctx, prev: TemplateVersion, new: TemplateVersion) -> None:
    """Copia definições de campos e tenta re-ancorar cada ocorrência no novo arquivo (contexto + trecho)."""
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for f in fields_service.fields_of_version(db, prev.id):
        nf = Field(
            workspace_id=f.workspace_id,
            version_id=new.id,
            name=f.name,
            label=f.label,
            type=f.type,
            description=f.description,
            required=f.required,
            default_value=f.default_value,
            example=f.example,
            mask=f.mask,
            group_name=f.group_name,
            position=f.position,
            include_in_batch=f.include_in_batch,
            config=f.config,
        )
        db.add(nf)
        db.flush()
        id_map[f.id] = nf.id
        for o in db.scalars(
            select(FieldOption).where(FieldOption.field_id == f.id).order_by(FieldOption.position)
        ):
            db.add(
                FieldOption(
                    workspace_id=o.workspace_id,
                    field_id=nf.id,
                    label=o.label,
                    value=o.value,
                    position=o.position,
                )
            )
    if not id_map:
        return
    blocks = {b.key: b for b in core.load_blocks(db, new.id) if b.kind == "paragraph"}
    occs = list(
        db.scalars(
            select(FieldOccurrence)
            .where(FieldOccurrence.version_id == prev.id)
            .order_by(FieldOccurrence.ordinal)
        )
    )
    for occ in occs:
        target = id_map.get(occ.field_id)
        if target is None or not occ.sample:
            continue
        pos = _find_anchor(blocks, occ)
        if pos is None:
            continue
        key, start = pos
        b = blocks[key]
        try:
            b.content, _ = replace_range_with_field(b.content, start, start + len(occ.sample), str(target))
        except RangeError:
            continue
        b.text = inline_text(b.content)
    db.flush()


def _find_anchor(blocks: dict[str, TemplateBlock], occ: FieldOccurrence) -> tuple[str, int] | None:
    """Localiza (bloco, offset) do trecho: mesma chave + contexto → qualquer bloco com contexto → mesma chave só pelo trecho."""
    sample = occ.sample
    want = occ.context_before[-15:] + sample + occ.context_after[:15]

    def hits(text: str) -> list[int]:
        return [m.start() for m in re.finditer(re.escape(sample), text)]

    same = blocks.get(occ.block_key)
    for b in ([same] if same else []) + [x for k, x in blocks.items() if k != occ.block_key]:
        for s in hits(b.text):
            seg = b.text[max(0, s - 15) : s + len(sample) + 15]
            matches_context = want in seg or (
                occ.context_before[-15:] in seg and occ.context_after[:15] in seg
            )
            if matches_context and not _covered(b, s, s + len(sample)):
                return b.key, s
    if same:
        for s in hits(same.text):
            if not _covered(same, s, s + len(sample)):
                return same.key, s
    return None


def _covered(b: TemplateBlock, start: int, end: int) -> bool:
    from app.docx_engine.nodes import iter_field_spans

    return any(s < end and start < e for s, e, _ in iter_field_spans(b.content))


# ------------------------------------------------------------------ editor


def version_out(v: TemplateVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version_number": v.version_number,
        "revision": v.revision,
        "analysis_status": v.analysis_status,
        "analysis_error": v.analysis_error,
        "note": v.note,
        "source_format": (v.meta or {}).get("source_format", "docx"),
        "created_at": v.created_at.isoformat(),
        "updated_at": v.updated_at.isoformat(),
    }


def source_filename(db: Session, v: TemplateVersion) -> str | None:
    """Nome do .docx enviado que originou a versão (para a interface dizer qual arquivo está em uso)."""
    if v.source_file_id is None:
        return None
    f = db.scalar(select(TemplateFile).where(TemplateFile.id == v.source_file_id))
    return f.original_filename if f else None


def get_editor(ctx: Ctx, generator_id: uuid.UUID) -> dict[str, Any]:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    version = core.current_version(db, gen)
    blocks = core.load_blocks(db, version.id)
    meta = version.meta or {}
    parts = [PartLike(**p) for p in meta.get("parts", [])]
    doc = blocks_to_doc(blocks, parts)
    return {
        "generator": generators_service.generator_out(db, gen),
        "version": {**version_out(version), "source_filename": source_filename(db, version)},
        "doc": doc,
        "fields": fields_service.list_out(db, version),
        "warnings": meta.get("warnings", []),
        "stats": meta.get("stats", {}),
    }


def _new_key(container: str, used: set[str], counters: dict[str, int]) -> str:
    n = counters.get(container, 0)
    while True:
        n += 1
        key = f"{container}/n{n}"
        if key not in used:
            counters[container] = n
            return key


def save_editor_doc(
    ctx: Ctx, generator_id: uuid.UUID, doc: dict[str, Any], base_revision: int
) -> dict[str, Any]:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    version = core.current_version(db, gen)
    if version.revision != base_revision:
        raise Conflict(
            "O documento foi alterado em outra aba ou dispositivo. Recarregue para continuar.",
            code="STALE_REVISION",
            details={"current_revision": version.revision},
        )
    try:
        incoming = list(walk_doc(doc))
    except DocStructureError as exc:
        raise ValidationFailed(str(exc), code="INVALID_DOCUMENT") from exc

    existing = {b.key: b for b in core.load_blocks(db, version.id)}
    known_fields = {str(f.id) for f in fields_service.fields_of_version(db, version.id)}
    used_keys = set(existing) | {b.key for b in incoming if b.key}
    counters: dict[str, int] = {}
    seen: set[str] = set()
    visible_containers = {b.container_key for b in incoming}
    warnings: list[str] = []
    last_original: dict[str, str] = {}  # container → última chave original vista (para clonar pPr)

    for bi in incoming:
        exists = (
            bi.key in existing and existing[bi.key].container_key == bi.container_key and bi.key not in seen
        )
        if bi.kind != "paragraph":
            if not exists or existing[bi.key or ""].kind != bi.kind:  # type: ignore[index]
                raise ValidationFailed(
                    "A estrutura de tabelas e elementos avançados não pode ser alterada no editor.",
                    code="STRUCTURE_LOCKED",
                )
            seen.add(bi.key or "")
            existing[bi.key or ""].ordinal = bi.ordinal
            continue
        content = _sanitize_content(bi.content, known_fields, warnings)
        text = inline_text(content)
        if exists:
            row = existing[bi.key or ""]
            if row.kind != "paragraph":
                raise ValidationFailed("Parágrafo inválido.", code="INVALID_DOCUMENT")
            seen.add(row.key)
            last_original[bi.container_key] = (
                row.key if row.origin == "original" else last_original.get(bi.container_key, row.key)
            )
            if row.content != content:
                row.content = content
                row.text = text
            row.ordinal = bi.ordinal
        else:
            key = _new_key(bi.container_key, used_keys, counters)
            used_keys.add(key)
            clone_of = last_original.get(bi.container_key)
            attrs = dict(existing[clone_of].attrs or {}) if clone_of and clone_of in existing else {}
            attrs.pop("hidden", None)
            attrs["clone_of"] = clone_of
            db.add(
                TemplateBlock(
                    workspace_id=ctx.workspace_id,
                    version_id=version.id,
                    key=key,
                    part=bi.part,
                    container_key=bi.container_key,
                    ordinal=bi.ordinal,
                    kind="paragraph",
                    origin="inserted",
                    content=content,
                    attrs=attrs,
                    text=text,
                    source_text="",
                )
            )
            seen.add(key)

    deleted = 0
    for key, row in existing.items():
        if key in seen or row.container_key not in visible_containers or (row.attrs or {}).get("hidden"):
            continue
        if row.kind != "paragraph":
            raise ValidationFailed(
                "A estrutura de tabelas e elementos avançados não pode ser alterada no editor.",
                code="STRUCTURE_LOCKED",
            )
        db.delete(row)
        deleted += 1
    db.flush()
    counts = core.recompute_occurrences(db, version)
    core.touch(version, gen, content=True)
    db.commit()
    return {
        "revision": version.revision,
        "occurrences": counts,
        "deleted_blocks": deleted,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _sanitize_content(
    nodes: list[dict[str, Any]], known_fields: set[str], warnings: list[str]
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for n in nodes:
        t = n.get("type")
        if t == "field":
            fid = (n.get("attrs") or {}).get("fieldId")
            if fid not in known_fields:  # campo inexistente: mantém o texto original como texto comum
                warnings.append("Um campo que não existe mais foi convertido em texto comum.")
                sample = (n.get("attrs") or {}).get("sample", "")
                if sample:
                    cleaned.append({"type": "text", "text": sample, "marks": n.get("marks", [])})
                continue
        if t in ("text", "hardBreak", "field", "docAtom"):
            cleaned.append(n)
        # nós desconhecidos (imagens coladas, etc.) são descartados
    return normalize_nodes(cleaned)


# ------------------------------------------------------------------ versões e publicação


def list_versions(ctx: Ctx, generator_id: uuid.UUID) -> list[dict[str, Any]]:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    rows = db.execute(
        select(TemplateVersion, User.name)
        .outerjoin(User, User.id == TemplateVersion.created_by)
        .where(TemplateVersion.generator_id == gen.id)
        .order_by(TemplateVersion.version_number.desc())
    ).all()
    out = []
    for v, author in rows:
        n_fields = len(fields_service.fields_of_version(db, v.id))
        out.append(
            {
                **version_out(v),
                "author": author,
                "fields_count": n_fields,
                "source_filename": source_filename(db, v),
            }
        )
    return out


def restore_version(ctx: Ctx, generator_id: uuid.UUID, version_id: uuid.UUID) -> TemplateVersion:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    src = core.get_version(db, ctx.workspace_id, version_id)
    if src.generator_id != gen.id:
        raise NotFound("Versão")
    if src.id == gen.current_version_id:
        raise Conflict("Esta já é a versão atual.", code="ALREADY_CURRENT")
    new = core.clone_version(db, src, gen, user_id=ctx.user.id, note=f"Restaurada da v{src.version_number}")
    gen.current_version_id = new.id
    gen.updated_at = utcnow()
    audit.record(
        db,
        "template.restore",
        ctx=ctx,
        entity_type="generator",
        entity_id=gen.id,
        meta={"from_version": src.version_number},
    )
    db.commit()
    return new


def block_specs(db: Session, version_id: uuid.UUID) -> list[BlockSpec]:
    return [
        BlockSpec(
            b.key,
            b.container_key,
            b.ordinal,
            b.kind,
            b.origin,
            b.content if b.kind == "paragraph" else None,
            b.attrs,
        )
        for b in core.load_blocks(db, version_id)
    ]


def compile_version(
    ctx: Ctx, gen: DocumentGenerator, version: TemplateVersion
) -> tuple[TemplateFile, CompileResult]:
    """Compila o gabarito (edições + tokens de campo) e o guarda como arquivo imutável."""
    db = ctx.db
    if version.source_file_id is None:
        raise ValidationFailed("Esta versão não tem arquivo de origem.", code="NO_SOURCE")
    src = core.get_file(db, ctx.workspace_id, version.source_file_id)
    original = get_storage().get(src.storage_key)
    names = {str(f.id): f.name for f in fields_service.fields_of_version(db, version.id)}
    result = compile_docx(original, block_specs(db, version.id), names)
    compiled = core.store_file(
        db,
        workspace_id=ctx.workspace_id,
        generator_id=gen.id,
        role="compiled",
        data=result.data,
        filename=f"{gen.name}.compiled.docx",
        user_id=ctx.user.id,
    )
    return compiled, result


def compile_current(ctx: Ctx, gen: DocumentGenerator) -> tuple[TemplateVersion, TemplateFile]:
    """Versão atual + seu gabarito compilado. Não há mais uma versão "publicada" separada — quem chama isto é a
    própria criação do job de geração —, então o resultado é cacheado em `compiled_file_id`/`compiled_revision`
    e só recompilado quando o conteúdo mudou (`revision` avançou). Cada job guarda sua própria cópia do
    compilado, então recompilar aqui nunca afeta gerações já feitas."""
    db = ctx.db
    version = core.current_version(db, gen)
    if version.compiled_file_id is not None and version.compiled_revision == version.revision:
        return version, core.get_file(db, ctx.workspace_id, version.compiled_file_id)
    try:
        compiled, _ = _retry(lambda: compile_version(ctx, gen, version))
    except TransientError as exc:
        raise ServiceUnavailable(
            "Não foi possível preparar o modelo para gerar agora (armazenamento indisponível). Tente novamente.",
            code="TEMPLATE_UNAVAILABLE",
        ) from exc
    version.compiled_file_id = compiled.id
    version.compiled_revision = version.revision
    db.commit()
    return version, compiled


def _retry[T](fn: Callable[[], T], tries: int = 3, base: float = 0.2) -> T:
    for attempt in range(tries):
        try:
            return fn()
        except TransientError:
            if attempt == tries - 1:
                raise
            time.sleep(base * (3**attempt))
    raise RuntimeError("inalcançável")


__all__ = ["BlockIn", "FieldSuggestion", "hashlib"]


def form_payload(ctx: Ctx, generator_id: uuid.UUID) -> dict[str, Any]:
    """Dados para o formulário individual e a prévia: campos + documento (com nós de campo) da versão atual."""
    from app.adapters.pdf import pdf_available

    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    v = core.current_version(db, gen)
    blocks = core.load_blocks(db, v.id)
    parts = [PartLike(**p) for p in (v.meta or {}).get("parts", [])]
    return {
        "generator": generators_service.generator_out(db, gen),
        "version": version_out(v),
        "fields": fields_service.list_out(db, v),
        "doc": blocks_to_doc(blocks, parts),
        "pdf_available": pdf_available(),
    }


def apply_field_to_block(
    ctx: Ctx,
    version: TemplateVersion,
    block_key: str,
    needle: str,
    field_id: uuid.UUID,
    *,
    occurrence: int = 0,
) -> bool:
    """Primitiva do servidor: troca `needle` no bloco por um nó de campo (usada por seed e por sugestões)."""
    db = ctx.db
    block = db.scalar(
        select(TemplateBlock).where(TemplateBlock.version_id == version.id, TemplateBlock.key == block_key)
    )
    if block is None or block.kind != "paragraph":
        return False
    idx = -1
    for _ in range(occurrence + 1):
        idx = block.text.find(needle, idx + 1)
        if idx < 0:
            return False
    try:
        block.content, _ = replace_range_with_field(block.content, idx, idx + len(needle), str(field_id))
    except RangeError:
        return False
    block.text = inline_text(block.content)
    db.flush()
    return True

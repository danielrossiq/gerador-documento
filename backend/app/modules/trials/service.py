"""Teste grátis na landing (D38): o visitante envia o documento dele, vê os campos marcados e cria a conta para
guardar o modelo.

Entrada pública e anônima — tratada como hostil:

* trava geral (TRIAL_ENABLED), campo-armadilha, Turnstile (quando configurado) e limites por IP real e por rede
  (/24 ou /64), com as chaves do limitador em HMAC (o IP não fica guardado em lugar nenhum);
* no máximo TRIAL_MAX_CONCURRENT testes em andamento no sistema todo (acima disso: "tente em instantes");
* arquivo validado pelos mesmos caminhos do upload (validate_docx; PDF só pelo conversor isolado, D35), até
  TRIAL_MAX_MB e TRIAL_MAX_PAGES; nada de gerar DOCX/PDF (LibreOffice é caro): só a análise;
* IA com orçamento diário próprio (TRIAL_AI_DAILY_BUDGET_USD, finalidade `trial` na razão de custo) lendo só o
  começo do documento; esgotou ou caiu → só as regras locais, sem custo;
* tudo some em TRIAL_TTL_MINUTES (limpeza) ou quando o teste vira modelo de uma conta (`claim`).

Nada do conteúdo vai para log: só formato, tamanho, códigos de erro e contagens.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
import threading
import time
import uuid
import zipfile
import zlib
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import PureWindowsPath
from typing import Any

import sqlalchemy as sa
from lxml import etree
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.adapters.queue import enqueue
from app.adapters.storage import get_storage
from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import (
    AppError,
    Conflict,
    LimitExceeded,
    ServiceUnavailable,
    TransientError,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.net import network_key
from app.core.security import new_token, token_hash
from app.db.base import utcnow
from app.db.models import AIAnalysisRun, TemplateFile, Trial
from app.db.session import get_factory
from app.docx_engine.editor_doc import PartLike, blocks_to_doc
from app.docx_engine.nodes import apply_fields
from app.docx_engine.parse import ParsedBlock, parse_docx
from app.docx_engine.pdf_import import convert_pdf, convert_pdf_remote, looks_like_pdf
from app.docx_engine.safety import DocxRejected, validate_docx
from app.modules.trials import turnstile

log = get_logger(__name__)

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
# Teste em andamento renova `heartbeat_at` a cada HEARTBEAT_EVERY; sem sinal há HEARTBEAT_STALE, o processo que o
# segurava morreu (API/worker reiniciado): não ocupa vaga e é encerrado (QA-6). Na fila há mais de QUEUED_GRACE,
# deixa de contar como vaga; há mais de QUEUED_DEAD, a mensagem se perdeu e o teste é encerrado.
HEARTBEAT_EVERY = 5
HEARTBEAT_STALE = timedelta(seconds=30)
QUEUED_GRACE = timedelta(seconds=90)
QUEUED_DEAD = timedelta(minutes=3)
CHARS_PER_PAGE = 4000  # estimativa folgada de página para .docx sem a contagem do Word (docProps/app.xml)
MAX_WAITING = 10  # envios esperando vaga ao mesmo tempo (cada um ocupa uma thread do pool por até 5 s)
ATTEMPTS_PER_HOUR = 30  # tentativas antes do Turnstile (só com ele ligado): limita chamadas à Cloudflare
# teto de achados (QA-4): brutos por parágrafo/no total antes de resolver sobreposições; e os que viram campo
RAW_PER_BLOCK, RAW_TOTAL = 100, 1500
MAX_HITS_PER_BLOCK, MAX_HITS = 30, 300
# .docx de visitante anônimo: bem menos que o upload das contas. Um .docx de 1 MB que descompacta para 78 MB levou
# 6,7 s e +523 MB de RAM no parse (medição da segurança); 25 MB descompactados bastam para 10 páginas com imagens.
DOCX_LIMITS = {"max_entries": 300, "max_entry_bytes": 15 * 1024 * 1024, "max_total_bytes": 25 * 1024 * 1024}
POLLS_PER_MINUTE = 120
CLAIMS_PER_HOUR = 20
_LOCK_KEY = 0x74726961  # "tria": trava consultiva da contagem de testes simultâneos (PostgreSQL)
_PURGE_EVERY_S = 300
_last_purge = 0.0

LIMIT_MESSAGE = (
    "Você já fez muitos testes por agora. Crie sua conta grátis para continuar, ou tente de novo mais tarde."
)
NOT_FOUND_MESSAGE = "Este teste expirou ou não existe. Envie o documento de novo."
FAILED_MESSAGE = (
    "Não foi possível ler este documento. Tente outro arquivo ou crie uma conta grátis para enviar."
)


class TrialNotFound(AppError):
    status_code = 404
    code = "TRIAL_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__(NOT_FOUND_MESSAGE)


def _key(value: str) -> str:
    """Chave do limitador sem o IP em claro (o Redis não guarda dado pessoal)."""
    mac = hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256)
    return mac.hexdigest()[:24]


def _max_bytes() -> int:
    return get_settings().trial_max_mb * 1024 * 1024


def public_config() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": s.trials_on,
        "max_mb": s.trial_max_mb,
        "max_pages": s.trial_max_pages,
        "accepts_pdf": s.pdf_import_mode != "off",
        "turnstile_site_key": s.turnstile_site_key if s.turnstile_secret else None,
        "ttl_minutes": s.trial_ttl_minutes,
    }


def _safe_filename(filename: str, fmt: str) -> str:
    name = PureWindowsPath(filename or "").name  # tira qualquer caminho (C:\..., ../)
    name = re.sub(r"[\x00-\x1f\x7f<>\"|?*]", "", name).strip()[:200]
    return name or f"documento.{fmt}"


def _check_file(data: bytes) -> str:
    """Formato (docx|pdf) depois das checagens baratas. O pesado (converter o PDF, ler o .docx) fica no worker."""
    max_bytes = _max_bytes()
    if not data:
        raise ValidationFailed("O arquivo está vazio.", code="EMPTY_FILE")
    if len(data) > max_bytes:
        raise ValidationFailed(
            f"O teste aceita arquivos de até {get_settings().trial_max_mb} MB.", code="FILE_TOO_LARGE"
        )
    if looks_like_pdf(data):
        if get_settings().pdf_import_mode == "off":
            raise ValidationFailed(
                "Por enquanto o teste aceita só documentos em Word (.docx).", code="PDF_IMPORT_DISABLED"
            )
        return "pdf"
    if data[:2] == b"PK":
        try:
            validate_docx(data, filename="documento.docx", max_bytes=max_bytes, **DOCX_LIMITS)
        except DocxRejected as exc:
            raise ValidationFailed(exc.message, code=exc.code) from exc
        return "docx"
    raise ValidationFailed(
        "Envie um documento do Word (.docx) ou um PDF digitado. Arquivo .doc antigo: salve como .docx no Word.",
        code="TRIAL_FILE_TYPE",
    )


def _lock(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})


def active_count(db: Session) -> int:
    now = utcnow()
    return int(
        db.scalar(
            select(func.count(Trial.id)).where(
                sa.or_(
                    sa.and_(Trial.status == "processing", Trial.heartbeat_at >= now - HEARTBEAT_STALE),
                    sa.and_(Trial.status == "queued", Trial.created_at >= now - QUEUED_GRACE),
                )
            )
        )
        or 0
    )


def fail_orphaned_trials(*, startup_thread_mode: bool = False) -> int:
    """Encerra testes que nenhum processo vivo segura (sem heartbeat; ou na fila há tempo demais). Na subida da API
    em modo `thread` (sem worker separado), tudo o que estava na fila ou em andamento morreu com o processo anterior."""
    now = utcnow()
    if startup_thread_mode:
        orphan = Trial.status.in_(("queued", "processing"))
    else:
        orphan = sa.or_(
            sa.and_(
                Trial.status == "processing",
                sa.or_(Trial.heartbeat_at.is_(None), Trial.heartbeat_at < now - HEARTBEAT_STALE),
            ),
            sa.and_(Trial.status == "queued", Trial.created_at < now - QUEUED_DEAD),
        )
    with get_factory()() as db:
        n = db.execute(
            update(Trial)
            .where(orphan)
            .values(status="failed", error_code="TRIAL_FAILED", error_message=FAILED_MESSAGE, finished_at=now)
        ).rowcount
        db.commit()
    if n:
        log.info("testes_orfaos_encerrados", extra={"n": int(n)})
    return int(n or 0)


def _busy() -> LimitExceeded:
    return LimitExceeded("Muita gente testando agora. Tente de novo em alguns segundos.", code="TRIAL_BUSY")


_WAITING = threading.BoundedSemaphore(MAX_WAITING)


def _wait_for_slot(db: Session) -> None:
    """Fila curta: com as vagas ocupadas, espera alguns segundos (TRIAL_BUSY_WAIT_SECONDS) antes de recusar. No máximo
    MAX_WAITING esperas ao mesmo tempo por processo: acima disso recusa na hora, sem prender threads do pool."""
    s = get_settings()
    if active_count(db) < s.trial_max_concurrent:
        return
    if not _WAITING.acquire(blocking=False):
        raise _busy()
    try:
        deadline = time.monotonic() + max(0.0, s.trial_busy_wait_seconds)
        while active_count(db) >= s.trial_max_concurrent:
            if time.monotonic() >= deadline:
                raise _busy()
            db.rollback()  # libera a leitura antes de esperar
            time.sleep(0.5)
    finally:
        _WAITING.release()


def _count_attempt(ipk: str, netk: str, hourly: int) -> None:
    s = get_settings()
    for key, limit, window in (
        (f"trial-ip-h:{ipk}", hourly, 3600),
        (f"trial-ip-d:{ipk}", s.trial_limit_ip_day, 86400),
        (f"trial-net-d:{netk}", s.trial_limit_net_day, 86400),
    ):
        ratelimit.check(key, limit, window, message=LIMIT_MESSAGE, code="TRIAL_RATE_LIMITED")


def _decoy(db: Session, size: int, fmt: str, filename: str) -> dict[str, Any]:
    """Armadilha (F2-5): grava um teste "falho" sem arquivo, que aparece como em processamento por alguns segundos e
    depois falha com a mensagem genérica — igual a um teste real que deu errado. Não ocupa vaga nem chama nada."""
    import secrets

    token = new_token(32)
    now = utcnow()
    db.add(
        Trial(
            token_hash=token_hash(token),
            status="failed",
            source_format=fmt,
            filename=_safe_filename(filename, fmt),
            size_bytes=size,
            storage_key=None,
            attempts=0,
            error_code="TRIAL_FAILED",
            error_message=FAILED_MESSAGE,
            created_at=now,
            finished_at=now + timedelta(seconds=6 + secrets.randbelow(9)),  # "termina" no futuro
            expires_at=now + timedelta(minutes=get_settings().trial_ttl_minutes),
        )
    )
    db.commit()
    log.info("teste_armadilha")
    return {
        "token": token,
        "status": "processing",
        "expires_at": (now + timedelta(minutes=get_settings().trial_ttl_minutes)).isoformat(),
    }


def create_trial(
    db: Session,
    *,
    ip: str | None,
    filename: str,
    data: bytes,
    turnstile_token: str | None,
    honeypot: str | None,
) -> dict[str, Any]:
    s = get_settings()
    if not s.trials_on:
        raise ServiceUnavailable("O teste grátis está desligado no momento.", code="TRIAL_DISABLED")
    # Os limites contam TENTATIVAS (requisito OBR-1 da segurança), antes de abrir o arquivo: recusa, falha da IA,
    # arquivo quebrado e até a armadilha gastam a vez. A landing confere tipo e tamanho antes de enviar.
    ipk, netk = _key(ip or "na"), _key(network_key(ip))
    # teto bruto por IP (inclui recusas do Turnstile e a armadilha): segura chamadas à Cloudflare e linhas falsas
    ratelimit.check(
        f"trial-try:{ipk}", ATTEMPTS_PER_HOUR, 3600, message=LIMIT_MESSAGE, code="TRIAL_RATE_LIMITED"
    )
    if honeypot:  # campo escondido preenchido: robô. Imita um teste de verdade que falhou; nada é processado.
        _count_attempt(ipk, netk, s.trial_limit_ip_hour)
        fmt = _check_file(
            data
        )  # arquivo inválido recebe a mesma recusa de sempre (a armadilha não se denuncia)
        return _decoy(db, len(data), fmt, filename)
    secret = s.turnstile_secret
    verified = False
    if secret:
        if not turnstile.verify(turnstile_token, ip, secret=secret):
            raise AppError(
                "Não conseguimos confirmar que você não é um robô. Marque a verificação e tente de novo.",
                code="TRIAL_CHALLENGE_FAILED",
                status_code=403,
            )
        verified = True
    # Com o desafio aprovado, o limite por IP por hora é maior: no Brasil muita gente sai pelo mesmo IP da operadora
    # (CGNAT do celular). O limite por /24 e o orçamento diário da IA continuam iguais.
    # sem vaga (TRIAL_BUSY) não desconta do limite por hora: o visitante não tem culpa (QA-6); só do teto bruto
    _wait_for_slot(db)
    _count_attempt(ipk, netk, s.trial_limit_ip_hour_verified if verified else s.trial_limit_ip_hour)
    fmt = _check_file(data)

    token = new_token(32)
    storage_key = f"trials/{uuid.uuid4().hex}.{fmt}"
    storage = get_storage()
    try:
        storage.put(storage_key, data, "application/octet-stream")
    except TransientError as exc:
        raise ServiceUnavailable(
            "Não foi possível receber o arquivo agora. Tente de novo.", code="TRIAL_UNAVAILABLE"
        ) from exc
    _lock(db)
    if (
        active_count(db) >= s.trial_max_concurrent
    ):  # recontagem sob a trava: dois envios juntos não furam o teto
        db.rollback()
        storage.delete(storage_key)
        raise _busy()
    now = utcnow()
    trial = Trial(
        token_hash=token_hash(token),
        status="queued",
        source_format=fmt,
        filename=_safe_filename(filename, fmt),
        size_bytes=len(data),
        storage_key=storage_key,
        attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=s.trial_ttl_minutes),
    )
    db.add(trial)
    db.commit()
    try:
        enqueue("trial", trial_id=str(trial.id))
    except Exception as exc:
        log.error("fila_indisponivel_para_teste", extra={"error_type": type(exc).__name__})
        _fail(db, trial, "TRIAL_UNAVAILABLE", "O teste está indisponível agora. Tente de novo em instantes.")
        raise ServiceUnavailable(
            "O teste está indisponível agora. Tente de novo em instantes.", code="TRIAL_UNAVAILABLE"
        ) from exc
    log.info("teste_recebido", extra={"format": fmt, "size": len(data)})
    return {"token": token, "status": "processing", "expires_at": trial.expires_at.isoformat()}


def _find(db: Session, token: str) -> Trial:
    if not TOKEN_RE.match(token or ""):
        raise TrialNotFound()
    trial = db.scalar(select(Trial).where(Trial.token_hash == token_hash(token)))
    if trial is None or trial.expires_at <= utcnow() or trial.claimed_at is not None:
        raise TrialNotFound()
    return trial


def get_status(db: Session, token: str, ip: str | None) -> dict[str, Any]:
    ratelimit.check(f"trial-poll:{_key(ip or 'na')}", POLLS_PER_MINUTE, 60)
    trial = _find(db, token)
    out: dict[str, Any] = {
        "status": trial.status,
        "filename": trial.filename,
        "format": trial.source_format,
        "expires_at": trial.expires_at.isoformat(),
        "ai": trial.ai_mode,
        "error": None,
        "result": None,
    }
    now = utcnow()
    dead = (
        trial.status == "processing" and (trial.heartbeat_at or trial.created_at) < now - HEARTBEAT_STALE
    ) or (trial.status == "queued" and trial.created_at < now - QUEUED_DEAD)
    if dead:
        out["status"] = "failed"  # o worker morreu no meio: a limpeza marca de vez
        out["error"] = {"code": "TRIAL_FAILED", "message": FAILED_MESSAGE}
    elif trial.status == "failed" and trial.finished_at and trial.finished_at > utcnow():
        out["status"] = "processing"  # armadilha: ainda "processando" (ver _decoy)
    elif trial.status == "failed":
        out["error"] = {
            "code": trial.error_code or "TRIAL_FAILED",
            "message": trial.error_message or FAILED_MESSAGE,
        }
    elif trial.status == "done" and trial.result:
        out["result"] = {
            k: v for k, v in trial.result.items() if k != "hits"
        }  # achados brutos ficam no servidor
    return out


# ------------------------------------------------------------------ processamento (worker)


def _fail(db: Session, trial: Trial, code: str, message: str) -> None:
    trial.status, trial.error_code, trial.error_message = "failed", code[:64], message[:300]
    trial.finished_at = utcnow()
    trial.result = None
    db.commit()


def run_trial_job(trial_id: str) -> None:
    """Ponto de entrada da fila. Idempotente: só quem passa o teste de `queued` para `processing` trabalha."""
    tid = uuid.UUID(trial_id)
    with get_factory()() as db:
        claimed = db.execute(
            update(Trial)
            .where(Trial.id == tid, Trial.status == "queued")
            .values(
                status="processing", started_at=utcnow(), heartbeat_at=utcnow(), attempts=Trial.attempts + 1
            )
        ).rowcount
        db.commit()
        if not claimed:
            return
        stop = threading.Event()
        threading.Thread(target=_heartbeat, args=(tid, stop), daemon=True, name="teste-heartbeat").start()
        trial = db.get(Trial, tid)
        assert trial is not None
        started = time.monotonic()
        try:
            _process_with_heartbeat(db, trial, stop)
        except DocxRejected as exc:
            db.rollback()
            _fail(db, db.get(Trial, tid) or trial, exc.code, exc.message)
            log.info("teste_recusado", extra={"code": exc.code})
        except AppError as exc:
            db.rollback()
            _fail(db, db.get(Trial, tid) or trial, exc.code, exc.message)
            log.info("teste_recusado", extra={"code": exc.code})
        except Exception as exc:  # nunca a mensagem/rastreamento: pode trazer trecho do documento
            db.rollback()
            _fail(db, db.get(Trial, tid) or trial, "TRIAL_FAILED", FAILED_MESSAGE)
            log.error("teste_falhou", extra={"error_type": type(exc).__name__})
        else:
            log.info(
                "teste_concluido",
                extra={
                    "ai": trial.ai_mode,
                    "fields": len((trial.result or {}).get("fields") or []),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )


def _heartbeat(tid: uuid.UUID, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_EVERY):
        try:
            with get_factory()() as db:
                db.execute(
                    update(Trial)
                    .where(Trial.id == tid, Trial.status == "processing")
                    .values(heartbeat_at=utcnow())
                )
                db.commit()
        except Exception:
            log.warning("teste_heartbeat_falhou")


def _process_with_heartbeat(db: Session, trial: Trial, stop: threading.Event) -> None:
    try:
        _process(db, trial)
    finally:
        stop.set()


def _docx_pages(data: bytes) -> int | None:
    """Páginas segundo o próprio Word (docProps/app.xml), quando ele gravou a contagem."""
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo("docProps/app.xml")
            if info.file_size > 256 * 1024:
                return None
            xml = zf.read(info)
    except (KeyError, zipfile.BadZipFile, OSError, zlib.error, EOFError):
        return None
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return None
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.endswith("}Pages") and (el.text or "").strip().isdigit():
            return int(el.text.strip())
    return None


def _too_long(max_pages: int) -> DocxRejected:
    return DocxRejected(
        "TRIAL_TOO_LONG",
        f"O teste aceita documentos de até {max_pages} páginas. Crie sua conta grátis para enviar documentos maiores.",
    )


def _process(db: Session, trial: Trial) -> None:
    from app.modules.suggestions.rules import adopt_semantic_names, detect_rules, resolve_overlaps
    from app.modules.suggestions.service import _number_duplicate_hits

    s = get_settings()
    storage = get_storage()
    if not trial.storage_key:
        raise DocxRejected("TRIAL_FAILED", FAILED_MESSAGE)
    data = storage.get(trial.storage_key)
    max_bytes = _max_bytes()
    warnings: list[str] = []
    if trial.source_format == "pdf":
        mode = s.pdf_import_mode
        if mode == "off":
            raise DocxRejected(
                "PDF_IMPORT_DISABLED", "Por enquanto o teste aceita só documentos em Word (.docx)."
            )
        if mode == "service":
            conv = convert_pdf_remote(
                data, url=s.pdf_converter_url or "", max_bytes=max_bytes, max_pages=s.trial_max_pages
            )
        else:
            conv = convert_pdf(data, max_bytes=max_bytes, max_pages=s.trial_max_pages)
        data = conv.docx
        # o .docx convertido vem de um leitor exposto a arquivo de fora: mesmas checagens de qualquer .docx
        validate_docx(data, filename="convertido.docx", max_bytes=4 * max_bytes, **DOCX_LIMITS)
        warnings.extend(conv.warnings[:3])
        new_key = f"trials/{uuid.uuid4().hex}.docx"
        storage.put(new_key, data, "application/octet-stream")
        old_key, trial.storage_key = trial.storage_key, new_key
        db.commit()
        storage.delete(old_key)
    else:
        validate_docx(data, filename="documento.docx", max_bytes=max_bytes, **DOCX_LIMITS)
        pages = _docx_pages(data)
        if pages is not None and pages > s.trial_max_pages:
            raise _too_long(s.trial_max_pages)
    try:
        parsed = parse_docx(data)
    except (etree.XMLSyntaxError, ValueError, KeyError, zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise DocxRejected(
            "DOCX_PARSE_FAILED",
            "Não foi possível ler o conteúdo do documento. Salve-o de novo no Word como .docx e tente outra vez.",
        ) from exc
    paragraphs = [
        b
        for b in parsed.blocks
        if b.kind == "paragraph" and not (b.attrs or {}).get("hidden") and b.text.strip()
    ]
    if not paragraphs:
        raise DocxRejected("EMPTY_DOCUMENT", "O documento não tem texto para transformar em modelo.")
    if sum(len(b.text) for b in paragraphs) > s.trial_max_pages * CHARS_PER_PAGE:
        raise _too_long(s.trial_max_pages)

    hits = _cap(detect_rules([(b.key, b.text) for b in paragraphs]), RAW_PER_BLOCK, RAW_TOTAL)
    ai_hits, ai_mode, ai_notes = _ai_hits(paragraphs)
    hits = _cap([*hits, *ai_hits], RAW_PER_BLOCK, RAW_TOTAL)
    # antes da numeração (que renomeia no lugar): o `claim` refaz o caminho todo com estes achados
    raw = [asdict(h) for h in hits]
    final = _number_duplicate_hits(adopt_semantic_names(resolve_overlaps(hits), hits))
    final = _cap(final, MAX_HITS_PER_BLOCK, MAX_HITS)
    doc, fields = _preview(parsed, final)
    trial.result = {
        "doc": doc,
        "fields": fields,
        "warnings": [*warnings, *ai_notes],
        "stats": {"paragraphs": len(paragraphs), "fields": len(fields)},
        "hits": raw,
    }
    trial.ai_mode = ai_mode
    trial.status = "done"
    trial.finished_at = utcnow()
    db.commit()


def _ai_hits(paragraphs: list[ParsedBlock]) -> tuple[list[Any], str, list[str]]:
    """Achados da IA (com orçamento diário próprio) ou das heurísticas locais. Nunca uma IA externa sem teto."""
    from app.adapters.ai import LocalHeuristicProvider, get_ai_provider
    from app.adapters.ai.base import AISuggestionRequest, AIUnavailable, BlockText
    from app.adapters.ai.openrouter import FIELDS_SYSTEM, build_blocks_prompt, max_output_tokens
    from app.modules import ai_budget
    from app.modules.assist import ai as assist_ai
    from app.modules.suggestions.rules import Hit, describe_location, infer_config

    s = get_settings()
    by_key = {b.key: b for b in paragraphs}
    texts = [BlockText(b.key, b.text, describe_location(b.key)) for b in paragraphs]

    def to_hits(res: Any, source: str) -> list[Hit]:
        out: list[Hit] = []
        for sug in res.suggestions:
            blk = by_key.get(sug.block)
            if blk is None:
                continue
            for m in re.finditer(re.escape(sug.text), blk.text):
                out.append(
                    Hit(
                        blk.key, m.start(), m.end(), sug.text, sug.name, sug.label, sug.type,
                        sug.confidence, source, sug.reason or "", infer_config(sug.type, sug.text),
                    )
                )  # fmt: skip
        return out

    provider = get_ai_provider()
    if provider is None:  # AI_PROVIDER=none: só as regras
        return [], "rules", []
    mode, notes = "local", []
    if provider.name == "openrouter" and s.trial_ai_daily_budget_usd > 0:
        request = AISuggestionRequest(texts, max_chars=s.trial_ai_max_chars)
        prompt, chars, truncated = build_blocks_prompt(request)
        try:
            spend_id = ai_budget.reserve(
                provider.model,
                "trial",
                assist_ai.worst_cost(
                    provider.model, len(FIELDS_SYSTEM) + len(prompt), max_output_tokens(chars)
                ),
                daily_cap_usd=Decimal(str(s.trial_ai_daily_budget_usd)),
            )
        except ai_budget.BudgetExceeded:
            mode = "budget"
        else:
            try:
                res = provider.suggest(request)
            except AIUnavailable:
                ai_budget.fail(spend_id)
            else:
                ai_budget.settle(
                    spend_id, getattr(provider, "last_cost_usd", None), res.tokens_in, res.tokens_out
                )
                if truncated:
                    notes.append(
                        "No teste, a IA leu só o começo do documento. Na sua conta, ela lê o documento inteiro."
                    )
                # o resto do documento (que a IA não leu) ainda passa pelas heurísticas locais, sem custo
                local = LocalHeuristicProvider().suggest(AISuggestionRequest(texts, max_chars=s.ai_max_chars))
                return [*to_hits(res, "ai"), *to_hits(local, "local")], "ai", notes
    # sem IA externa (desligada, sem chave, orçamento do dia esgotado ou fora do ar): heurísticas locais, sem custo.
    # Provedor externo sem teto por finalidade (Anthropic direto) nunca é usado para visitante anônimo.
    local = LocalHeuristicProvider().suggest(AISuggestionRequest(texts, max_chars=s.ai_max_chars))
    return to_hits(local, "local"), mode, notes


def _cap(hits: list[Any], per_block: int, total: int) -> list[Any]:
    """Teto de achados do teste (QA-4): os de maior confiança de cada parágrafo, depois em ordem do documento.
    Um parágrafo de 38 mil caracteres cheio de datas/CPFs gerava ~3.600 achados e prendia o worker por 2 minutos."""
    by_block: dict[str, list[Any]] = {}
    for h in hits:
        by_block.setdefault(h.block_key, []).append(h)
    kept: list[Any] = []
    for items in by_block.values():
        kept.extend(sorted(items, key=lambda x: (-x.confidence, x.start))[:per_block])
    kept.sort(key=lambda x: (x.block_key, x.start))
    return kept[:total]


def _preview(parsed: Any, hits: list[Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Documento (mesmo JSON do editor) com cada achado virando um nó de campo + a lista de campos encontrados.
    Uma passada por parágrafo (`apply_fields`), não um `replace_range_with_field` por achado (QA-4)."""
    ids: dict[str, str] = {}
    meta: dict[str, Any] = {}
    fields: dict[str, dict[str, Any]] = {}
    per_block: dict[str, list[Any]] = {}
    for h in sorted(hits, key=lambda x: (x.block_key, x.start)):
        per_block.setdefault(h.block_key, []).append(h)
        fid = ids.setdefault(h.name, f"t{len(ids) + 1}")
        meta.setdefault(fid, h)
    blocks = []
    for b in parsed.blocks:
        content = b.content
        if b.kind == "paragraph" and b.key in per_block:
            spans = [(h.start, h.end, ids[h.name]) for h in per_block[b.key]]
            content, applied = apply_fields(b.content, spans)
            for _, _, fid in applied:
                h = meta[fid]
                f = fields.setdefault(
                    fid,
                    {
                        "id": fid,
                        "name": h.name[:64],
                        "label": h.label[:200],
                        "type": h.type,
                        "sample": h.text[:200],
                        "count": 0,
                        "source": h.source,
                        "confidence": round(float(h.confidence), 2),
                    },
                )
                f["count"] += 1
        blocks.append(dataclasses.replace(b, content=content))
    parts = [PartLike(p.name, p.kind, p.label, p.hidden) for p in parsed.parts]
    order = {fid: i for i, fid in enumerate(ids.values())}
    return blocks_to_doc(blocks, parts), sorted(fields.values(), key=lambda f: order[f["id"]])


# ------------------------------------------------------------------ teste → modelo da conta


def claim(ctx: Ctx, token: str) -> dict[str, Any]:
    """Cria o modelo na conta com o documento e as sugestões do teste (sem nova análise nem custo de IA)."""
    from app.adapters.ai import PROMPT_VERSION
    from app.modules.audit import service as audit
    from app.modules.generators import service as generators_service
    from app.modules.suggestions.rules import RULES_VERSION, Hit
    from app.modules.suggestions.service import _readable_blocks, materialize
    from app.modules.templates import service as templates_service

    db = ctx.db
    ratelimit.check(f"trial-claim:{ctx.user.id}", CLAIMS_PER_HOUR, 3600)
    trial = _find(db, token)
    if trial.status != "done" or not trial.storage_key or not trial.result:
        raise Conflict(
            "O documento ainda está sendo analisado. Aguarde alguns segundos.", code="TRIAL_NOT_READY"
        )
    taken = db.execute(
        update(Trial)
        .where(Trial.id == trial.id, Trial.claimed_at.is_(None))
        .values(claimed_at=utcnow(), claimed_workspace_id=ctx.workspace_id)
    ).rowcount
    db.commit()
    if not taken:
        raise TrialNotFound()
    storage_key = trial.storage_key
    hits = list((trial.result or {}).get("hits") or [])
    try:
        data = get_storage().get(storage_key)
        parsed = parse_docx(data)
        stem = re.sub(r"\.(docx|pdf)$", "", trial.filename, flags=re.I).strip() or "Meu documento"
        gen = generators_service.create_generator(ctx, stem, None)
        version = templates_service.create_version(
            ctx,
            gen,
            filename=trial.filename,
            data=data,
            parsed=parsed,
            warnings=list(parsed.warnings),
            source_format=trial.source_format,
            analyze=False,
        )
        blocks = _readable_blocks(db, version)
        src = db.get(TemplateFile, version.source_file_id)
        text_hash = hashlib.sha256("\n".join(f"{b.key}\t{b.text}" for b in blocks).encode()).hexdigest()
        run = AIAnalysisRun(
            workspace_id=ctx.workspace_id,
            generator_id=gen.id,
            version_id=version.id,
            file_sha256=hashlib.sha256(f"{src.sha256 if src else ''}|{text_hash}".encode()).hexdigest(),
            provider="openrouter" if trial.ai_mode == "ai" else "local",
            model=None,
            # sufixo próprio: "Analisar de novo" não reaproveita este resultado (a IA do teste leu só o começo)
            prompt_version=f"{PROMPT_VERSION}-{RULES_VERSION}-trial",
            status="succeeded",
            result={"hits": hits, "warnings": []},
            finished_at=utcnow(),
            duration_ms=0,
        )
        db.add(run)
        db.flush()
        materialize(db, version, [Hit(**h) for h in hits], blocks)
        version.analysis_status = "done"
        trial.claimed_generator_id = gen.id
        trial.result = None
        audit.record(
            db,
            "trial.claim",
            ctx=ctx,
            entity_type="generator",
            entity_id=gen.id,
            meta={"format": trial.source_format, "ai": trial.ai_mode, "hits": len(hits)},
        )
        db.commit()
    except Exception:
        db.rollback()
        db.execute(
            update(Trial).where(Trial.id == trial.id).values(claimed_at=None, claimed_workspace_id=None)
        )  # devolve o teste: a pessoa pode tentar de novo (ex.: depois de liberar espaço no plano)
        db.commit()
        raise
    try:
        get_storage().delete(storage_key)  # o modelo da conta tem a própria cópia
    except TransientError:
        log.warning(
            "teste_arquivo_nao_apagado"
        )  # fica a chave na linha: a limpeza apaga quando o teste vencer
    else:
        trial.storage_key = None
        db.commit()
    return {"generator_id": str(gen.id), "next": f"/generators/{gen.id}/edit"}


# ------------------------------------------------------------------ limpeza


def purge_expired_trials() -> dict[str, int]:
    """Apaga arquivo e linha dos testes vencidos e encerra os que ficaram presos no meio (worker caiu)."""
    storage = get_storage()
    removed = failed = 0
    now = utcnow()
    fail_orphaned_trials()
    with get_factory()() as db:
        rows = db.scalars(select(Trial).where(Trial.expires_at <= now).limit(1000)).all()
        done_ids = []
        for t in rows:
            if t.storage_key:
                try:
                    storage.delete(t.storage_key)
                except TransientError:
                    failed += 1
                    continue
            done_ids.append(t.id)
        if done_ids:
            db.execute(delete(Trial).where(Trial.id.in_(done_ids)))
            removed = len(done_ids)
        db.commit()
    if removed or failed:
        log.info("testes_expirados_removidos", extra={"removidos": removed, "falhas": failed})
    return {"removidos": removed, "falhas": failed}


def purge_expired_trials_throttled() -> None:
    """Chamado pelo watchdog (a cada ~15 s): limpa no máximo a cada 5 minutos por processo."""
    global _last_purge
    if time.monotonic() - _last_purge < _PURGE_EVERY_S:
        return
    _last_purge = time.monotonic()
    purge_expired_trials()

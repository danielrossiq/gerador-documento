"""“Cole aqui e a gente descobre o modelo”: dada uma tabela colada (cabeçalho + algumas linhas), encontra
qual modelo do espaço de trabalho ela preenche e como cada coluna vira um campo.

Como as colunas casam com os campos, em ordem de confiança:
  * nome — o cabeçalho é o rótulo ou o código do campo (sem acento/pontuação/“*”);
  * parecido — grafia próxima (mesmo corte de 0,82 da importação de planilha) ou um contido no outro
    (“CPF” ↔ “CPF do contratante”), dividindo a confiança quando o mesmo nome serve a vários campos;
  * conteúdo — a coluna não tem nome conhecido, mas todos os valores são CPF (ou CNPJ, e-mail, data, CEP)
    e o modelo tem exatamente um campo desse tipo ainda sem coluna;
  * semântico — opcional, só quando não há correspondência exata e o classificador de papéis (TypeSafe/Jev,
    o mesmo dos kits) está configurado: colunas e campos que sobraram são classificados juntos e casados
    pelo mesmo papel (“nome da pessoa contratante”, “valor do aluguel”…). Entra como sugestão, nunca
    como correspondência exata.

A pontuação de cada modelo combina quantas colunas foram usadas (precisão) e quantos campos do lote foram
preenchidos (cobertura), ponderadas pela confiança; campos obrigatórios sem coluna pesam contra.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from statistics import mean
from typing import Any

from sqlalchemy import select

from app.core.deps import Ctx
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.db.models import DocumentGenerator
from app.modules.fields import service as fields_service
from app.modules.fields.normalize import is_empty, normalize_value
from app.modules.fields.types import FieldDef, normalize_key

log = get_logger(__name__)

MAX_COLUMNS = 100
MAX_SAMPLE_ROWS = 30
SIMILARITY_CUTOFF = 0.82
MIN_CONFIDENCE = 0.5
# reconhecíveis só pelo conteúdo; data antes de CEP porque "01/02/2027" também tem 8 dígitos
STRONG_TYPES = ("cpf", "cnpj", "email", "date", "cep")
TEXT_TYPES = frozenset({"text_short", "text_long"})
STOPWORDS = frozenset({"de", "do", "da", "dos", "das", "e", "o", "a", "os", "as", "no", "na", "em"})
PASTE_ID = "__colado__"


@dataclass(frozen=True)
class ColumnMatch:
    column: int
    header: str
    field: str
    label: str
    confidence: float
    source: str  # nome | parecido | conteudo | semantico


@dataclass
class Candidate:
    generator_id: str
    name: str
    matches: list[ColumnMatch]
    missing_required: list[str]
    unmatched_columns: list[str]
    batch_fields: int
    score: float = 0.0
    exact: bool = False
    defs: list[FieldDef] = field(default_factory=list, repr=False)


# ------------------------------------------------------------------ correspondência (funções puras)


def clean_header(h: str) -> str:
    """Tira marcas de obrigatório da planilha-modelo (“Nome *”, “CPF (obrigatório)”)."""
    return re.sub(r"\s*(\*|\(obrigat[oó]rio\))\s*$", "", h or "", flags=re.IGNORECASE).strip()


def _tokens(text: str) -> set[str]:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in STOPWORDS}


def _contained(header: str, label: str) -> bool:
    a, b = _tokens(header), _tokens(label)
    if not a or not b or not any(len(t) >= 3 for t in a & b):
        return False
    return a <= b or b <= a


def values_fit(fd: FieldDef, values: list[str]) -> float | None:
    """Fração dos valores de exemplo aceitos pelo tipo do campo (None se a coluna veio vazia)."""
    filled = [v for v in values if not is_empty(v)]
    if not filled:
        return None
    ok = sum(1 for v in filled if normalize_value(replace(fd, required=False), v)[1] is None)
    return ok / len(filled)


def infer_type(values: list[str], *, extended: bool = False) -> str | None:
    """Tipo que TODOS os valores preenchidos aceitam. `extended` também tenta valor/número/telefone —
    ambíguos demais para casar sozinhos, mas úteis como pista para o classificador semântico."""
    filled = [v for v in values if not is_empty(v)]
    if len(filled) < 1:
        return None
    for t in (*STRONG_TYPES, *(("currency", "number", "phone") if extended else ())):
        probe = FieldDef(id="", name="x", label="x", type=t)
        if values_fit(probe, filled) == 1.0:
            return t
    return None


def header_looks_like_data(headers: list[str]) -> bool:
    """A 1ª linha colada parece dado, não cabeçalho (tabela colada sem a linha de títulos): alguma célula é um
    CPF, CNPJ, e-mail, data, CEP, valor, número ou telefone. Nesse caso os "títulos" são dados pessoais — não vão
    para o classificador externo."""
    return any(infer_type([h], extended=True) is not None for h in headers if h.strip())


def match_columns(headers: list[str], samples: list[list[str]], defs: list[FieldDef]) -> list[ColumnMatch]:
    batch = [d for d in defs if d.include_in_batch]
    pairs: list[tuple[float, int, FieldDef, str]] = []
    for ci, raw in enumerate(headers):
        h = clean_header(raw)
        hn = normalize_key(h)
        if not hn:
            continue
        contained = [d for d in batch if _contained(h, d.label) or _contained(h, d.name.replace("_", " "))]
        for d in batch:
            keys = {k for k in (normalize_key(d.label), normalize_key(d.name)) if k}
            if hn in keys:
                conf, src = 1.0, "nome"
            else:
                ratio = max((difflib.SequenceMatcher(None, hn, k).ratio() for k in keys), default=0.0)
                if ratio >= SIMILARITY_CUTOFF:
                    conf, src = 0.95 * ratio, "parecido"
                elif d in contained:
                    conf, src = 0.75 / len(contained) ** 0.5, "parecido"
                else:
                    continue
            if d.type not in TEXT_TYPES:
                fit = values_fit(d, samples[ci])
                if fit is not None and fit < 0.5:
                    conf *= (
                        0.5  # nome parecido, mas os valores não são desse tipo (ex.: datas num campo de CPF)
                    )
            pairs.append((conf, ci, d, src))

    chosen: dict[int, ColumnMatch] = {}
    used: set[str] = set()
    for conf, ci, d, src in sorted(pairs, key=lambda p: -p[0]):
        if conf < MIN_CONFIDENCE or ci in chosen or d.name in used:
            continue
        chosen[ci] = ColumnMatch(ci, headers[ci], d.name, d.label, round(conf, 3), src)
        used.add(d.name)

    for ci, raw in enumerate(headers):  # pelo conteúdo: coluna de CPFs → o único campo de CPF que sobrou
        if ci in chosen:
            continue
        t = infer_type(samples[ci])
        if t is None:
            continue
        free = [d for d in batch if d.type == t and d.name not in used]
        if len(free) == 1:
            chosen[ci] = ColumnMatch(ci, raw, free[0].name, free[0].label, 0.66, "conteudo")
            used.add(free[0].name)
    return [chosen[i] for i in sorted(chosen)]


def score(cand: Candidate, headers: list[str]) -> Candidate:
    batch = [d for d in cand.defs if d.include_in_batch]
    mapped = {m.field for m in cand.matches}
    required = [d for d in batch if d.required and (d.default is None or d.default == "")]
    cand.missing_required = [d.label for d in required if d.name not in mapped]
    cols = [i for i, h in enumerate(headers) if normalize_key(clean_header(h))]
    matched_cols = {m.column for m in cand.matches}
    cand.unmatched_columns = [headers[i] for i in cols if i not in matched_cols]
    if not cand.matches or not batch or not cols:
        cand.score, cand.exact = 0.0, False
        return cand
    precision = len(matched_cols & set(cols)) / len(cols)
    coverage = len(mapped) / len(batch)
    penalty = 0.15 * len(cand.missing_required) / max(1, len(required))
    cand.score = round(
        max(0.0, mean(m.confidence for m in cand.matches) * (0.55 * precision + 0.45 * coverage) - penalty), 3
    )
    cand.exact = (
        not cand.unmatched_columns
        and not cand.missing_required
        and all(m.confidence >= 0.99 for m in cand.matches)
    )
    return cand


def candidate_for(
    generator_id: str, name: str, defs: list[FieldDef], headers: list[str], samples: list[list[str]]
) -> Candidate:
    cand = Candidate(generator_id, name, match_columns(headers, samples, defs), [], [], 0, defs=defs)
    cand.batch_fields = sum(1 for d in defs if d.include_in_batch)
    return score(cand, headers)


# ------------------------------------------------------------------ sugestão semântica (opcional)


def _semantic_pass(cands: list[Candidate], headers: list[str], samples: list[list[str]]) -> bool:
    """Casa colunas e campos que sobraram pelo papel (classificador TypeSafe/Jev). Devolve se rodou."""
    from app.adapters.ai import RoleClassifierUnavailable, get_role_classifier
    from app.modules.kits.matching import (
        AUTO_MERGEABLE_TYPES,
        TEXT_TYPES_NEED_ATTRIBUTE,
        RoleCandidate,
    )
    from app.modules.kits.matching import MIN_CONFIDENCE as ROLE_MIN

    classifier = get_role_classifier()
    if classifier is None or not cands:
        return False
    rc: list[RoleCandidate] = []
    col_ids: dict[str, int] = {}
    matched_by_cand = {c.generator_id: {m.column for m in c.matches} for c in cands}
    pending_cols = sorted(
        {
            i
            for c in cands
            for i, h in enumerate(headers)
            if normalize_key(clean_header(h)) and i not in matched_by_cand[c.generator_id]
        }
    )
    for i in pending_cols:
        t = infer_type(samples[i], extended=True) or "text_short"
        example = next((v for v in samples[i] if not is_empty(v)), None)
        fd = FieldDef(
            id=f"col{i}", name=f"coluna_{i}", label=clean_header(headers[i]), type=t, example=example
        )
        cid = f"c{len(rc)}"
        rc.append(RoleCandidate(cid, PASTE_ID, "Tabela colada", fd, t in TEXT_TYPES_NEED_ATTRIBUTE))
        col_ids[cid] = i
    field_ids: dict[str, tuple[Candidate, FieldDef]] = {}
    for c in cands:
        used = {m.field for m in c.matches}
        for d in c.defs:
            if d.include_in_batch and d.name not in used and d.type in AUTO_MERGEABLE_TYPES:
                cid = f"c{len(rc)}"
                rc.append(RoleCandidate(cid, c.generator_id, c.name, d, d.type in TEXT_TYPES_NEED_ATTRIBUTE))
                field_ids[cid] = (c, d)
    if not col_ids or not field_ids:
        return False
    try:
        answers = classifier.classify(rc)
    except RoleClassifierUnavailable as exc:
        log.warning("identificacao_semantica_indisponivel", extra={"code": exc.code})
        return False

    def key(cid: str, needs_attr: bool, ftype: str) -> tuple[str, ...] | None:
        a = answers.get(cid)
        if a is None or a.role_confidence < ROLE_MIN:
            return None
        if needs_attr:
            if a.attribute is None or (a.attribute_confidence or 0) < ROLE_MIN:
                return None
            return (a.role, "attr", a.attribute)
        return (a.role, "type", ftype)

    col_keys = {cid: key(cid, r.needs_attribute, r.field.type) for r in rc if (cid := r.id) in col_ids}
    for c in cands:
        taken_cols = {m.column for m in c.matches}
        taken_fields = {m.field for m in c.matches}
        for fid, (owner, d) in field_ids.items():
            if owner is not c or d.name in taken_fields:
                continue
            needs = d.type in TEXT_TYPES_NEED_ATTRIBUTE
            fk = key(fid, needs, d.type)
            if fk is None:
                continue
            for cid, ck in col_keys.items():
                ci = col_ids[cid]
                # texto casa pelo (papel, atributo); os demais pelo (papel, tipo) — o tipo da coluna vem do conteúdo
                if ck is None or ci in taken_cols or ck != fk:
                    continue
                c.matches.append(ColumnMatch(ci, headers[ci], d.name, d.label, 0.6, "semantico"))
                taken_cols.add(ci)
                taken_fields.add(d.name)
                break
        c.matches.sort(key=lambda m: m.column)
        score(c, headers)
        c.exact = False  # sugestão semântica nunca é "exata": o usuário confirma
    return True


# ------------------------------------------------------------------ serviço


def _clean_table(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    headers = [str(h or "").strip()[:200] for h in headers[:MAX_COLUMNS]]
    samples: list[list[str]] = [[] for _ in headers]
    for r in rows[:MAX_SAMPLE_ROWS]:
        for i in range(len(headers)):
            samples[i].append(str(r[i]).strip()[:300] if i < len(r) and r[i] is not None else "")
    return headers, samples


def candidate_out(c: Candidate) -> dict[str, Any]:
    return {
        "generator_id": c.generator_id,
        "name": c.name,
        "score": c.score,
        "exact": c.exact,
        "batch_fields": c.batch_fields,
        "mapping": [
            {
                "column": m.column,
                "header": m.header,
                "field": m.field,
                "label": m.label,
                "confidence": m.confidence,
                "source": m.source,
            }
            for m in c.matches
        ],
        "missing_required": c.missing_required,
        "unmatched_columns": c.unmatched_columns,
    }


def identify(
    ctx: Ctx,
    headers: list[str],
    rows: list[list[str]],
    *,
    generator_id: uuid.UUID | None = None,
    semantic: bool = True,
) -> dict[str, Any]:
    """Com `generator_id` (a pessoa escolheu o modelo na mão), avalia só ele e devolve o mapeamento mesmo fraco."""
    headers, samples = _clean_table(headers, rows)
    headerless = header_looks_like_data(headers)
    if headerless:  # a "linha de títulos" é a 1ª linha de dados: entra nas amostras (casamento pelo conteúdo)
        samples = [[h, *col] for h, col in zip(headers, samples, strict=True)]
    query = select(DocumentGenerator).where(
        DocumentGenerator.workspace_id == ctx.workspace_id,
        DocumentGenerator.deleted_at.is_(None),
        DocumentGenerator.current_version_id.is_not(None),
    )
    if generator_id is not None:
        query = query.where(DocumentGenerator.id == generator_id)
    else:
        query = query.where(DocumentGenerator.status != "archived")
    gens = ctx.db.scalars(query.order_by(DocumentGenerator.updated_at.desc())).all()
    if generator_id is not None and not gens:
        raise NotFound("Modelo")
    cands: list[Candidate] = []
    for g in gens:
        assert g.current_version_id is not None
        defs = fields_service.field_defs(ctx.db, g.current_version_id)
        if not any(d.include_in_batch for d in defs):
            continue
        c = candidate_for(str(g.id), g.name, defs, headers, samples)
        if c.matches or generator_id is not None:
            cands.append(c)
    cands.sort(key=lambda c: (-c.exact, -c.score, c.name.lower()))

    semantic_used = False
    if semantic and not headerless and not (cands and cands[0].exact):
        top = (
            cands[:3]
            if cands
            else [
                candidate_for(
                    str(g.id),
                    g.name,
                    fields_service.field_defs(ctx.db, g.current_version_id),
                    headers,
                    samples,
                )
                for g in gens[:3]
                if g.current_version_id is not None
            ]
        )
        semantic_used = _semantic_pass(top, headers, samples)
        if semantic_used:
            known = {c.generator_id for c in cands}
            cands.extend(c for c in top if c.generator_id not in known and c.matches)
            cands.sort(key=lambda c: (-c.exact, -c.score, c.name.lower()))

    shown = cands[:1] if generator_id is not None else [c for c in cands if c.score >= 0.2][:3]
    best = shown[0] if shown else None
    status = "none"
    if best is not None:
        status = (
            "exact"
            if best.exact
            else "probable"
            if best.score >= 0.45 and not best.missing_required
            else "weak"
        )
    return {
        "status": status,
        "semantic": semantic_used,
        "header_looks_like_data": headerless,
        "columns": headers,
        "candidates": [candidate_out(c) for c in shown],
    }

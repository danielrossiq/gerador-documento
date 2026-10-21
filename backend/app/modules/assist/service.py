"""Recursos de IA para quem usa o modelo (D33):

- `fill`: a pessoa cola um texto (e-mail, WhatsApp, ficha do cliente) e a IA distribui os dados nos campos.
  O servidor confere cada valor com a mesma validação da geração (CPF, data, valor…) antes de devolver.
- `review`: antes de gerar, a IA lê o documento já preenchido e aponta incoerências (datas, nomes, concordância,
  valores). Só aponta: não muda nada sozinha.

Privacidade: vai para a IA só o necessário (rótulos dos campos + o texto colado; ou o texto do documento com os
valores). Nada disso é gravado: a razão de custo guarda só workspace, finalidade, modelo, tokens e custo.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from app.adapters.ai.base import AIUnavailable
from app.core.deps import Ctx
from app.core.errors import Conflict, ValidationFailed
from app.modules import ai_budget
from app.modules.assist import ai
from app.modules.audit import service as audit
from app.modules.fields import service as fields_service
from app.modules.fields.normalize import format_value, normalize_value
from app.modules.fields.types import FieldDef
from app.modules.templates import core

MAX_FILL_CHARS = 8_000
MAX_REVIEW_CHARS = 24_000
MAX_ISSUES = 8

FILL_SYSTEM = """Você preenche formulários de documentos de escritório (contratos, procurações, recibos) a partir de um
texto colado pela pessoa: um e-mail, uma mensagem de WhatsApp, uma ficha de cliente, uma assinatura de e-mail.

Para cada campo do formulário, procure o valor no texto. Regras:
- só use o que está no texto; se não houver, devolva value "" (nunca invente);
- formatos: datas dd/mm/aaaa; valores em reais 1.234,56; CPF 000.000.000-00; CNPJ 00.000.000/0000-00; CEP 00000-000;
  telefone (00) 00000-0000; Sim/Não para campos de Sim/Não;
- campos de lista: escolha uma das opções dadas só se o texto indicar claramente qual é; senão "";
- nomes com a grafia do texto; endereço completo numa linha só.
"evidence": o trecho do texto em que o valor apareceu (até 12 palavras), ou "".
"""

REVIEW_SYSTEM = """Você revisa um documento de escritório brasileiro JÁ PREENCHIDO antes de ele ser gerado. Os dados variáveis
aparecem entre ⟦ ⟧ com o código do campo; a lista CAMPOS dá o nome de cada código. Aponte só problemas concretos de
preenchimento, por exemplo:
- datas em ordem impossível (término antes do início) ou prazo que não bate com início e término;
- a mesma pessoa ou empresa escrita de formas diferentes; dados de uma parte no lugar de outra;
- concordância de gênero/número com a pessoa ("inscrita" para um homem, "o locatária");
- valor por extenso que não corresponde ao número; percentuais ou prazos incoerentes entre si;
- campo importante vazio.
É normal e NÃO deve ser apontado: assinar antes do início da vigência, datas futuras, campos opcionais vazios.
NÃO comente redação jurídica, estilo, cláusulas ou legislação, e não dê aconselhamento jurídico.
Se estiver tudo coerente, devolva a lista vazia. No máximo 8 apontamentos, do mais grave ao mais leve.
"field": o código do campo (sem ⟦ ⟧) ou "" se não for de um campo. "severity": "alta", "media" ou "baixa".
"message": em português, direto, até 25 palavras, dizendo o que conferir; cite o campo pelo NOME, nunca pelo código."""


def _fill_schema(names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value", "evidence"],
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "value": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                },
            }
        },
    }


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "severity", "message"],
                "properties": {
                    "field": {"type": "string"},
                    "severity": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    "message": {"type": "string"},
                },
            },
        }
    },
}


def _describe(fd: FieldDef) -> str:
    kind = {
        "text_short": "texto",
        "text_long": "texto longo",
        "number": "número",
        "currency": "valor em reais",
        "date": "data",
        "cpf": "CPF",
        "cnpj": "CNPJ",
        "cep": "CEP",
        "email": "e-mail",
        "phone": "telefone",
        "oab": "OAB",
        "select": "lista",
        "yes_no": "Sim/Não",
        "checkbox": "Sim/Não",
    }.get(fd.type, "texto")
    line = f'- {fd.name}: "{fd.label}" ({kind})'
    if fd.type == "select" and fd.options:
        line += " opções: " + " | ".join(o.label for o in fd.options[:40])
    return line


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def _grounded(source: str, value: str, evidence: str) -> bool:
    """O valor veio mesmo do texto colado? Modelos às vezes "completam" (ex.: escolhem uma opção da lista sem
    nada no texto). Vale se o trecho citado estiver no texto (ou quase: 80% das palavras), ou se o próprio valor
    estiver — comparando sem acento/pontuação, e só dígitos para CPF, CNPJ, CEP, telefone e datas numéricas."""
    plain_src = _plain(source)
    ev = _plain(evidence)
    if ev and ev in plain_src:
        return True
    words = [w for w in ev.split() if len(w) >= 3]
    vocab = set(plain_src.split())
    if words and sum(w in vocab for w in words) / len(words) >= 0.8:
        return True
    val = _plain(value)
    if val and val in plain_src:
        return True
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 6 and digits in re.sub(r"\D", "", source)


def _call(ctx: Ctx, purpose: str, **kw: Any):  # type: ignore[no-untyped-def]
    # a reserva de custo usa uma transação própria (vale mesmo se esta requisição cair): libera a da requisição antes
    ctx.db.commit()
    try:
        return ai.guarded_chat(purpose=purpose, workspace_id=ctx.workspace_id, quota=ctx.limit("max_ai_actions_per_month"), **kw)
    except ai.AIDisabled as exc:
        raise Conflict("A IA não está ativada neste ambiente.", code="AI_DISABLED") from exc
    except ai_budget.BudgetExceeded as exc:
        raise Conflict(str(exc), code=exc.code) from exc
    except AIUnavailable as exc:
        raise Conflict("A IA não respondeu agora. Tente de novo em instantes.", code=exc.code) from exc


def _require_ai() -> None:
    if not ai.enabled():
        raise Conflict("A IA não está ativada neste ambiente.", code="AI_DISABLED")


def fill_values(ctx: Ctx, defs: list[FieldDef], text: str, *, entity: tuple[str, uuid.UUID]) -> dict[str, Any]:
    text = (text or "").strip()
    if len(text) < 3:
        raise ValidationFailed("Cole o texto com os dados do cliente.", code="AI_FILL_EMPTY")
    defs = [d for d in defs if d.type != "checkbox"]
    if not defs:
        raise ValidationFailed("Este formulário não tem campos para preencher.", code="AI_FILL_NO_FIELDS")
    clipped = text[:MAX_FILL_CHARS]
    user = "CAMPOS DO FORMULÁRIO:\n" + "\n".join(_describe(d) for d in defs) + "\n\nTEXTO COLADO:\n" + clipped
    res = _call(
        ctx,
        "fill",
        system=FILL_SYSTEM,
        user=user,
        schema_name="preenchimento",
        schema=_fill_schema([d.name for d in defs]),
        max_tokens=1500 + 80 * len(defs),  # folga para modelos que raciocinam antes de responder
    )
    by_name = {d.name: d for d in defs}
    values: dict[str, str] = {}
    invalid: dict[str, str] = {}
    evidence: dict[str, str] = {}
    dropped = 0
    for item in res.data.get("values") or []:
        name, raw = item.get("name"), str(item.get("value") or "").strip()
        fd = by_name.get(name)
        if not fd or not raw or name in values:
            continue
        if not _grounded(clipped, raw, str(item.get("evidence") or "")):
            dropped += 1  # não estava no texto: fica em branco (a pessoa preenche), em vez de um valor inventado
            continue
        _, err = normalize_value(fd, raw)
        if err:
            invalid[name] = err  # vai assim mesmo: a pessoa vê o erro no próprio campo e corrige
        values[name] = raw  # o formulário aplica a máscara/formato do tipo ao receber
        if item.get("evidence"):
            evidence[name] = str(item["evidence"])[:160]
    audit.record(ctx.db, "assist.fill", ctx=ctx, entity_type=entity[0], entity_id=entity[1], meta={"found": len(values), "invalid": len(invalid), "dropped": dropped, "chars": len(clipped)})
    ctx.db.commit()
    return {
        "values": values,
        "invalid": invalid,
        "evidence": evidence,
        "missing": [d.name for d in defs if d.name not in values],
        "truncated": len(text) > MAX_FILL_CHARS,
    }


def fill_generator(ctx: Ctx, generator_id: uuid.UUID, text: str) -> dict[str, Any]:
    _require_ai()
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    version = core.current_version(ctx.db, gen)
    return fill_values(ctx, fields_service.field_defs(ctx.db, version.id), text, entity=("generator", gen.id))


def fill_kit(ctx: Ctx, kit_id: uuid.UUID, text: str) -> dict[str, Any]:
    from app.modules.kits import service as kits_service

    _require_ai()
    kit = kits_service.get_kit(ctx.db, ctx.workspace_id, kit_id)
    return fill_values(ctx, kits_service.kit_field_defs(ctx.db, kit.id), text, entity=("kit", kit.id))


def _document_with_values(ctx: Ctx, version, defs: list[FieldDef], values: dict[str, Any]) -> str:  # type: ignore[no-untyped-def]
    by_id = {d.id: d for d in defs}
    loaded = core.load_blocks(ctx.db, version.id)
    blocks = core.ordered_blocks(loaded, core.part_order_of(version, loaded))
    lines: list[str] = []
    used = 0
    for b in blocks:
        if b.kind != "paragraph" or (b.attrs or {}).get("hidden"):
            continue
        parts: list[str] = []
        for n in b.content or []:
            t = n.get("type")
            if t == "text":
                parts.append(n.get("text", ""))
            elif t == "hardBreak":
                parts.append(" ")
            elif t == "field":
                fd = by_id.get(str((n.get("attrs") or {}).get("fieldId")))
                if fd is None:
                    continue
                raw = values.get(fd.name)
                canonical, err = normalize_value(fd, raw)
                shown = format_value(fd, canonical) if not err and canonical not in (None, "") else (str(raw) if raw else "")
                parts.append(f"⟦{fd.name}: {shown or '(vazio)'}⟧")
        line = "".join(parts).strip()
        if not line:
            continue
        if used + len(line) > MAX_REVIEW_CHARS:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def review_generator(ctx: Ctx, generator_id: uuid.UUID, values: dict[str, Any]) -> dict[str, Any]:
    _require_ai()
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    version = core.current_version(ctx.db, gen)
    defs = fields_service.field_defs(ctx.db, version.id)
    doc = _document_with_values(ctx, version, defs, values or {})
    if not doc:
        raise ValidationFailed("O documento está vazio.", code="AI_REVIEW_EMPTY")
    legend = "CAMPOS:\n" + "\n".join(f"- {d.name} = {d.label}" for d in defs)
    user = f"{legend}\n\nDOCUMENTO:\n{doc}"
    res = _call(ctx, "review", system=REVIEW_SYSTEM, user=user, schema_name="revisao", schema=REVIEW_SCHEMA, max_tokens=3000)
    names = {d.name: d.label for d in defs}
    issues = []
    for it in (res.data.get("issues") or [])[:MAX_ISSUES]:
        msg = str(it.get("message") or "").strip()
        if not msg:
            continue
        field = it.get("field") if it.get("field") in names else ""
        issues.append({"field": field, "label": names.get(field or "", ""), "severity": it.get("severity") or "media", "message": msg[:300]})
    audit.record(ctx.db, "assist.review", ctx=ctx, entity_type="generator", entity_id=gen.id, meta={"issues": len(issues)})
    ctx.db.commit()
    return {"issues": issues}


def status(ctx: Ctx) -> dict[str, Any]:
    with_ai = ai.enabled()
    return {
        "enabled": with_ai,
        "actions_used": ai_budget.actions_this_month(ctx.db, ctx.workspace_id) if with_ai else 0,
        "actions_limit": ctx.limit("max_ai_actions_per_month"),
    }

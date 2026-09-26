"""Sugestão de campos compartilhados de um kit: agrupa campos parecidos (mesmo tipo, nome/rótulo próximo)
entre geradores diferentes. Puramente funcional — sem acesso a banco — para ser fácil de testar isoladamente.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from app.modules.fields.types import FieldDef, normalize_key, to_snake_case, unique_name

# Tipos "de dados pessoais/simples": seguros para juntar automaticamente porque o valor não depende de opções
# configuradas por documento. `select`/`yes_no`/`checkbox` ficam de fora do auto-detect (o usuário pode
# mapear manualmente se quiser) — o conjunto de opções costuma ser específico de cada documento.
AUTO_MERGEABLE_TYPES = frozenset(
    {"text_short", "text_long", "number", "currency", "date", "cpf", "cnpj", "cep", "email", "phone"}
)
SIMILARITY_CUTOFF = (
    0.82  # mesmo limiar da sugestão de mapeamento da importação de planilha (app.modules.generation.imports)
)


@dataclass(frozen=True)
class MemberFields:
    generator_id: str
    generator_name: str
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class SuggestedKitField:
    name: str
    label: str
    type: str
    required: bool
    mask: str | None
    example: str | None
    config: dict[str, Any] = field(default_factory=dict)
    mapping: dict[str, str] = field(
        default_factory=dict
    )  # generator_id -> nome técnico do campo naquele gerador


def suggest_kit_fields(members: list[MemberFields]) -> list[SuggestedKitField]:
    """Agrupa campos do MESMO tipo com nome/rótulo parecido, presentes em pelo menos 2 geradores diferentes.

    Um campo que só existe em um único gerador não é "compartilhado" — fica de fora (continua preenchível como
    campo próprio daquele documento no formulário do kit). Nunca junta dois campos do mesmo gerador num só
    campo do kit. O resultado é só uma sugestão inicial: nomes, tipos e o mapeamento continuam editáveis.
    """
    buckets: dict[str, list[tuple[str, str, FieldDef]]] = {}
    for m in members:
        for f in m.fields:
            if f.type not in AUTO_MERGEABLE_TYPES:
                continue
            key = normalize_key(f.label) or normalize_key(f.name)
            if not key:
                continue
            buckets.setdefault(f.type, []).append((m.generator_id, key, f))

    groups: list[SuggestedKitField] = []
    used_names: set[str] = set()
    for items in buckets.values():
        remaining = list(items)
        while remaining:
            seed_gid, seed_key, seed_field = remaining.pop(0)
            cluster: dict[str, FieldDef] = {seed_gid: seed_field}
            still: list[tuple[str, str, FieldDef]] = []
            for gid, key, f in remaining:
                if gid in cluster:
                    still.append((gid, key, f))  # este gerador já tem um campo no grupo: não entra de novo
                    continue
                close = key == seed_key or difflib.get_close_matches(
                    seed_key, [key], n=1, cutoff=SIMILARITY_CUTOFF
                )
                (cluster.__setitem__(gid, f) if close else still.append((gid, key, f)))
            remaining = still
            if len(cluster) < 2:
                continue  # não compartilhado: fica como campo próprio do documento
            rep = seed_field
            name = unique_name(to_snake_case(rep.label, fallback="campo"), used_names)
            used_names.add(name)
            groups.append(
                SuggestedKitField(
                    name=name,
                    label=rep.label,
                    type=rep.type,
                    required=any(f.required for f in cluster.values()),
                    mask=rep.mask,
                    example=rep.example,
                    config=dict(rep.config),
                    mapping={gid: f.name for gid, f in cluster.items()},
                )
            )
    groups.sort(key=lambda g: (-len(g.mapping), g.label.lower()))
    return groups


# ---------------------------------------------------------------------------------------------------------
# Classificação semântica de papéis (opcional, via TypeSafe/Jev — ver docs/DECISIONS.md D24). Em vez de só
# comparar o TEXTO do rótulo, cada campo candidato é classificado em (a) qual parte do documento ele
# descreve — para nunca juntar "Nome do contratante" com "Nome do contratado", que são pessoas diferentes —
# e, para campos de texto livre, (b) que tipo de informação é (nome, endereço, cargo…), já que o tipo do
# campo (`text_short`) sozinho não distingue "Nome" de "Cargo". Tudo aqui continua puramente funcional: quem
# chama a IA (com timeout/retry/fallback) é o adaptador em app.adapters.ai.typesafe; este módulo só monta os
# candidatos e agrupa a resposta já validada.

ROLE_CRITERIA: dict[str, str] = {
    "parte_a": (
        "A parte que dá origem ao documento, contrata, compra, outorga, empresta ou é o "
        "titular/solicitante principal (ex.: contratante, comprador, outorgante, locador, credor, "
        "requerente, emitente)."
    ),
    "parte_b": (
        "A parte que presta o serviço, vende, recebe a outorga, aluga, toma emprestado ou é a "
        "contraparte principal (ex.: contratado, vendedor, outorgado, locatário, devedor, destinatário)."
    ),
    "terceiro": "Testemunha, fiador, avalista ou representante legal — não é nenhuma das partes principais.",
    "nao_e_parte": (
        "Não identifica uma pessoa ou empresa específica — é um dado do próprio documento (valor, data, "
        "objeto, prazo, número de processo, cláusula…)."
    ),
}

ATTRIBUTE_CRITERIA: dict[str, str] = {
    "nome": "Nome de uma pessoa física ou razão social de uma empresa.",
    "endereco": "Endereço, logradouro ou domicílio.",
    "cargo_profissao": "Cargo, profissão ou função.",
    "objeto": "Objeto do documento, descrição do serviço/produto ou trecho de uma cláusula específica.",
    "outro": "Nenhuma das anteriores.",
}

# Só campos de texto livre precisam da segunda pergunta (atributo): tipos como cpf/cnpj/data/moeda já dizem
# por si só que informação é — só falta saber de qual parte (a primeira pergunta, papel, resolve isso).
TEXT_TYPES_NEED_ATTRIBUTE = frozenset({"text_short", "text_long"})
MIN_CONFIDENCE = 0.6


@dataclass(frozen=True)
class RoleCandidate:
    id: str  # "c0", "c1"… — chave usada nas perguntas enviadas ao classificador
    generator_id: str
    generator_name: str
    field: FieldDef
    needs_attribute: bool


@dataclass(frozen=True)
class RoleAnswer:
    role: str
    role_confidence: float
    attribute: str | None = None
    attribute_confidence: float | None = None


def build_role_candidates(members: list[MemberFields]) -> list[RoleCandidate]:
    """Mesmo filtro de tipos/rótulo vazio do agrupamento por similaridade, só que sem agrupar ainda —
    a resposta do classificador é que decide os grupos (ver `suggest_kit_fields_by_role`)."""
    candidates: list[RoleCandidate] = []
    n = 0
    for m in members:
        for f in m.fields:
            if f.type not in AUTO_MERGEABLE_TYPES:
                continue
            if not (normalize_key(f.label) or normalize_key(f.name)):
                continue
            candidates.append(
                RoleCandidate(
                    id=f"c{n}",
                    generator_id=m.generator_id,
                    generator_name=m.generator_name,
                    field=f,
                    needs_attribute=f.type in TEXT_TYPES_NEED_ATTRIBUTE,
                )
            )
            n += 1
    return candidates


def suggest_kit_fields_by_role(
    candidates: list[RoleCandidate], answers: dict[str, RoleAnswer]
) -> list[SuggestedKitField]:
    """Agrupa candidatos com a MESMA resposta do classificador — (papel, atributo) para texto livre,
    (papel, tipo) para os demais —, presentes em pelo menos 2 geradores diferentes. Respostas com confiança
    abaixo de `MIN_CONFIDENCE` (papel OU atributo) não são usadas para agrupar: o campo fica de fora do kit
    em vez de arriscar juntar errado — o mapeamento manual continua disponível para esses casos."""
    buckets: dict[tuple[str, ...], list[RoleCandidate]] = {}
    for c in candidates:
        ans = answers.get(c.id)
        if ans is None or ans.role_confidence < MIN_CONFIDENCE:
            continue
        if c.needs_attribute:
            if ans.attribute is None or (ans.attribute_confidence or 0) < MIN_CONFIDENCE:
                continue
            key = (ans.role, "attr", ans.attribute)
        else:
            key = (ans.role, "type", c.field.type)
        buckets.setdefault(key, []).append(c)

    groups: list[SuggestedKitField] = []
    used_names: set[str] = set()
    for items in buckets.values():
        cluster: dict[str, FieldDef] = {}
        for c in items:
            if c.generator_id in cluster:
                continue  # este gerador já tem um campo neste grupo: não entra de novo
            cluster[c.generator_id] = c.field
        if len(cluster) < 2:
            continue  # não compartilhado: fica como campo próprio do documento
        rep = items[0].field
        name = unique_name(to_snake_case(rep.label, fallback="campo"), used_names)
        used_names.add(name)
        groups.append(
            SuggestedKitField(
                name=name,
                label=rep.label,
                type=rep.type,
                required=any(f.required for f in cluster.values()),
                mask=rep.mask,
                example=rep.example,
                config=dict(rep.config),
                mapping={gid: f.name for gid, f in cluster.items()},
            )
        )
    groups.sort(key=lambda g: (-len(g.mapping), g.label.lower()))
    return groups


def unclustered_candidates(
    candidates: list[RoleCandidate], role_suggestions: list[SuggestedKitField]
) -> list[RoleCandidate]:
    """Candidatos que o agrupamento por papel NÃO usou — seja porque a confiança não bateu, seja porque
    bateu mas ficaram "órfãos" (confiantes num papel que nenhum outro gerador recebeu, então o grupo nunca
    chegou a 2 geradores). É importante incluir os órfãos aqui, não só os de baixa confiança: dois campos
    "Nome completo" idênticos podem ter confiança em lados OPOSTOS do corte (ex.: 0.7 e 0.51) — se cada um
    fosse decidido isoladamente, o confiante ficaria sozinho (grupo descartado) e o outro, sozinho no
    "resto", sem achar o parceiro certo. Comparar contra o resultado JÁ AGRUPADO evita essa armadilha:
    o que não entrou em nenhum grupo de verdade volta pra heurística por similaridade (`candidates_to_members`
    + `suggest_kit_fields`), que não depende de confiança — só de o rótulo/tipo baterem."""
    used = {(gid, fname) for sug in role_suggestions for gid, fname in sug.mapping.items()}
    return [c for c in candidates if (c.generator_id, c.field.name) not in used]


def candidates_to_members(candidates: list[RoleCandidate]) -> list[MemberFields]:
    """Reagrupa candidatos (uma lista achatada) de volta por gerador — o formato que `suggest_kit_fields`
    espera — para rodar a heurística por similaridade só nesse subconjunto."""
    by_gen: dict[str, list[FieldDef]] = {}
    name_by_gen: dict[str, str] = {}
    for c in candidates:
        by_gen.setdefault(c.generator_id, []).append(c.field)
        name_by_gen[c.generator_id] = c.generator_name
    return [MemberFields(gid, name_by_gen[gid], tuple(fields)) for gid, fields in by_gen.items()]


def merge_suggestion_lists(*lists: list[SuggestedKitField]) -> list[SuggestedKitField]:
    """Combina sugestões de mais de uma passada (ex.: papel + similaridade no que sobrou) num resultado só,
    fundindo grupos que caírem no mesmo (rótulo normalizado, tipo) em vez de criar dois campos duplicados."""
    by_key: dict[tuple[str, str], SuggestedKitField] = {}
    order: list[tuple[str, str]] = []
    for lst in lists:
        for sug in lst:
            key = (normalize_key(sug.label), sug.type)
            prev = by_key.get(key)
            if prev is None:
                by_key[key] = sug
                order.append(key)
                continue
            mapping = dict(prev.mapping)
            for gid, fname in sug.mapping.items():
                mapping.setdefault(gid, fname)  # gerador já presente: mantém o valor da primeira passada
            by_key[key] = SuggestedKitField(
                name=prev.name,
                label=prev.label,
                type=prev.type,
                required=prev.required or sug.required,
                mask=prev.mask,
                example=prev.example,
                config=prev.config,
                mapping=mapping,
            )
    groups = [g for k in order if len((g := by_key[k]).mapping) >= 2]
    groups.sort(key=lambda g: (-len(g.mapping), g.label.lower()))
    return groups

"""Agrupamento de campos parecidos entre geradores (sugestão de campos compartilhados de um kit)."""

from __future__ import annotations

from app.modules.fields.types import FieldDef
from app.modules.kits.matching import (
    MemberFields,
    RoleAnswer,
    build_role_candidates,
    candidates_to_members,
    merge_suggestion_lists,
    suggest_kit_fields,
    suggest_kit_fields_by_role,
    unclustered_candidates,
)


def fd(name: str, label: str, type_: str, **kw) -> FieldDef:
    return FieldDef(id=name, name=name, label=label, type=type_, **kw)


def test_same_name_and_type_across_generators_is_grouped():
    """O agrupamento é por proximidade de TEXTO (rótulo/nome normalizado), não por significado — rótulos
    idênticos (a forma mais comum na prática: o usuário nomeia os campos de forma parecida) sempre casam."""
    members = [
        MemberFields("g1", "Contrato", (fd("nome_do_contratante", "Nome do contratante", "text_short"),)),
        MemberFields("g2", "Procuração", (fd("nome_completo", "Nome do contratante", "text_short"),)),
    ]
    out = suggest_kit_fields(members)
    assert len(out) == 1
    g = out[0]
    assert g.type == "text_short" and set(g.mapping) == {"g1", "g2"}
    assert g.mapping["g1"] == "nome_do_contratante" and g.mapping["g2"] == "nome_completo"


def test_field_only_in_one_generator_is_not_grouped():
    members = [
        MemberFields("g1", "Contrato", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g2", "Termo", (fd("valor", "Valor", "currency"),)),
    ]
    assert suggest_kit_fields(members) == []


def test_different_types_never_merge_even_with_identical_label():
    members = [
        MemberFields("g1", "A", (fd("cpf", "CPF", "cpf"),)),
        MemberFields("g2", "B", (fd("cpf", "CPF", "text_short"),)),  # mesmo rótulo, tipo diferente
    ]
    assert suggest_kit_fields(members) == []


def test_two_fields_from_the_same_generator_never_join_one_group():
    """Duas variações do "mesmo" campo dentro de UM gerador não podem virar um único campo do kit."""
    members = [
        MemberFields(
            "g1",
            "A",
            (
                fd("nome_contratante", "Nome do contratante", "text_short"),
                fd("nome_testemunha", "Nome da testemunha", "text_short"),
            ),
        ),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    out = suggest_kit_fields(members)
    # cada grupo tem no máximo 1 campo de g1
    for g in out:
        assert len([gid for gid in g.mapping if gid == "g1"]) <= 1


def test_select_and_yes_no_are_not_auto_merged():
    """Tipos com opções configuráveis por documento ficam fora do auto-detect (mapeamento manual, se o usuário quiser)."""
    members = [
        MemberFields("g1", "A", (fd("tipo", "Tipo de serviço", "select"),)),
        MemberFields("g2", "B", (fd("tipo", "Tipo de serviço", "select"),)),
        MemberFields("g3", "C", (fd("renovacao", "Renovação automática", "yes_no"),)),
        MemberFields("g4", "D", (fd("renovacao", "Renovação automática", "yes_no"),)),
    ]
    assert suggest_kit_fields(members) == []


def test_required_is_true_if_any_member_requires_it():
    members = [
        MemberFields("g1", "A", (fd("cpf", "CPF", "cpf", required=False),)),
        MemberFields("g2", "B", (fd("cpf", "CPF", "cpf", required=True),)),
    ]
    out = suggest_kit_fields(members)
    assert out[0].required is True


def test_unrelated_labels_are_not_grouped_just_for_sharing_a_substring():
    members = [
        MemberFields("g1", "A", (fd("cep", "CEP", "cep"),)),
        MemberFields("g2", "B", (fd("cep_residencial", "CEP residencial", "cep"),)),
    ]
    # "CEP" x "CEP residencial" normalizados: "cep" x "cepresidencial" — não são próximos o bastante por
    # padrão do difflib; o importante é que closeness exige textos bem parecidos, não qualquer substring.
    assert suggest_kit_fields(members) == []


def test_near_identical_labels_with_a_typo_are_still_grouped():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome do contratante", "text_short"),)),
        MemberFields("g2", "B", (fd("nome2", "Nome do contratente", "text_short"),)),  # erro de digitação
    ]
    out = suggest_kit_fields(members)
    assert len(out) == 1 and set(out[0].mapping) == {"g1", "g2"}


def test_three_generators_sharing_a_field_group_together():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g3", "C", (fd("nome", "Nome", "text_short"),)),
    ]
    out = suggest_kit_fields(members)
    assert len(out) == 1 and len(out[0].mapping) == 3


def test_generated_names_are_unique_and_snake_case():
    members = [
        MemberFields("g1", "A", (fd("a", "Nome do Contratante", "text_short"),)),
        MemberFields("g2", "B", (fd("b", "Nome do Contratante", "text_short"), fd("c", "CPF", "cpf"))),
        MemberFields("g3", "C", (fd("d", "CPF", "cpf"),)),
    ]
    out = suggest_kit_fields(members)
    names = [g.name for g in out]
    assert len(names) == len(set(names))
    assert all(n == n.lower() and " " not in n for n in names)


# ---------------------------------------------------------------------------------------------------------
# Agrupamento semântico (classificador externo opcional — ver docs/DECISIONS.md D24). Diferente do teste
# acima (que é por TEXTO), aqui a resposta do classificador já vem pronta (simulada) — só o agrupamento é
# testado; a chamada HTTP em si tem seus próprios testes em test_kit_role_classifier.py.


def test_role_based_grouping_keeps_different_party_roles_apart():
    """O caso que motivou a feature: "Nome do contratante" e "Nome do contratado" têm rótulo parecido mas
    são PESSOAS DIFERENTES — o agrupamento por papel não pode juntá-los num campo só."""
    members = [
        MemberFields(
            "g1",
            "Contrato A",
            (
                fd("nome_contratante", "Nome do contratante", "text_short"),
                fd("nome_contratado", "Nome do contratado", "text_short"),
            ),
        ),
        MemberFields(
            "g2",
            "Contrato B",
            (
                fd("nome_contratante", "Nome do contratante", "text_short"),
                fd("nome_contratado", "Nome do contratado", "text_short"),
            ),
        ),
    ]
    candidates = build_role_candidates(members)
    answers = {
        c.id: RoleAnswer(
            role="parte_a" if c.field.label == "Nome do contratante" else "parte_b",
            role_confidence=0.9,
            attribute="nome",
            attribute_confidence=0.9,
        )
        for c in candidates
    }
    out = suggest_kit_fields_by_role(candidates, answers)
    assert len(out) == 2  # um grupo por papel, nunca os dois juntos
    labels = {g.label for g in out}
    assert labels == {"Nome do contratante", "Nome do contratado"}
    for g in out:
        assert set(g.mapping) == {"g1", "g2"}


def test_role_based_grouping_merges_synonyms_that_text_similarity_would_miss():
    """ "Nome completo" (g1) e "Nome do contratante" (g2) não têm rótulo parecido (o teste equivalente por
    texto não junta), mas se o classificador der o MESMO papel+atributo para os dois, viram um campo só."""
    members = [
        MemberFields("g1", "Procuração", (fd("nome_completo", "Nome completo", "text_short"),)),
        MemberFields("g2", "Contrato", (fd("nome_contratante", "Nome do contratante", "text_short"),)),
    ]
    # confirma a premissa: por texto puro, não junta
    assert suggest_kit_fields(members) == []

    candidates = build_role_candidates(members)
    answers = {
        c.id: RoleAnswer(role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9)
        for c in candidates
    }
    out = suggest_kit_fields_by_role(candidates, answers)
    assert len(out) == 1 and set(out[0].mapping) == {"g1", "g2"}


def test_role_based_grouping_ignores_low_confidence_role():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    answers = {
        candidates[0].id: RoleAnswer(
            role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9
        ),
        candidates[1].id: RoleAnswer(
            role="parte_a", role_confidence=0.4, attribute="nome", attribute_confidence=0.9
        ),  # abaixo de MIN_CONFIDENCE
    }
    assert suggest_kit_fields_by_role(candidates, answers) == []


def test_role_based_grouping_ignores_low_confidence_attribute_for_text_fields():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    answers = {
        candidates[0].id: RoleAnswer(
            role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9
        ),
        candidates[1].id: RoleAnswer(
            role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.3
        ),  # atributo pouco confiável
    }
    assert suggest_kit_fields_by_role(candidates, answers) == []


def test_role_based_grouping_never_merges_two_fields_from_the_same_generator():
    members = [
        MemberFields(
            "g1",
            "A",
            (
                fd("nome_contratante", "Nome do contratante", "text_short"),
                fd("nome_testemunha", "Nome da testemunha", "text_short"),
            ),
        ),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    # classificador (hipotético, e errado de propósito) dá o MESMO papel/atributo para os dois campos de g1
    answers = {
        c.id: RoleAnswer(role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9)
        for c in candidates
    }
    out = suggest_kit_fields_by_role(candidates, answers)
    for g in out:
        assert len([gid for gid in g.mapping if gid == "g1"]) <= 1


def test_role_based_grouping_non_text_types_dont_need_attribute():
    """CPF/CNPJ/data/moeda já dizem por si só que informação é — só o papel importa para diferenciar."""
    members = [
        MemberFields("g1", "A", (fd("cpf_contratante", "CPF do contratante", "cpf"),)),
        MemberFields("g2", "B", (fd("cpf", "CPF", "cpf"),)),
    ]
    candidates = build_role_candidates(members)
    answers = {c.id: RoleAnswer(role="parte_a", role_confidence=0.9) for c in candidates}  # sem atributo
    out = suggest_kit_fields_by_role(candidates, answers)
    assert len(out) == 1 and out[0].type == "cpf" and set(out[0].mapping) == {"g1", "g2"}


def test_build_role_candidates_excludes_select_and_yes_no_types():
    """Mesmo filtro `AUTO_MERGEABLE_TYPES` do caminho por similaridade — ver test_select_and_yes_no_are_not_auto_merged."""
    members = [
        MemberFields("g1", "A", (fd("tipo", "Tipo", "select"), fd("cpf", "CPF", "cpf"))),
    ]
    candidates = build_role_candidates(members)
    assert [c.field.name for c in candidates] == ["cpf"]


# ---------------------------------------------------------------------------------------------------------
# Caminho híbrido: candidatos que o classificador não teve confiança pra decidir (ex.: rótulo comum demais,
# sem contexto de qual parte) voltam pra heurística por similaridade em vez de ficarem de fora — sem isso,
# um rótulo IDÊNTICO em dois documentos poderia deixar de ser agrupado só por indecisão do classificador,
# regressão em relação ao D24 original que este caminho existe pra evitar.


def test_unclustered_candidates_excludes_fields_that_ended_up_in_a_role_group():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome", "text_short"),)),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    answers = {
        c.id: RoleAnswer(role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9)
        for c in candidates
    }
    role_suggestions = suggest_kit_fields_by_role(candidates, answers)
    assert len(role_suggestions) == 1  # os dois casaram
    assert unclustered_candidates(candidates, role_suggestions) == []


def test_unclustered_candidates_keeps_a_confident_but_partnerless_field():
    """Achado testando contra a API real: um campo pode ter confiança suficiente para o SEU papel mas não
    ter par (nenhum outro gerador caiu no mesmo papel+atributo) — o grupo nunca chega a 2 geradores e é
    descartado por `suggest_kit_fields_by_role`. Sem devolver esse candidato pro "resto", ele simplesmente
    desaparece — mesmo tendo, por exemplo, um gêmeo de baixa confiança em outro gerador esperando por ele
    na heurística por similaridade (ver test_hybrid_recovers... logo abaixo)."""
    members = [MemberFields("g1", "A", (fd("nome", "Nome", "text_short"),))]
    candidates = build_role_candidates(members)
    answers = {
        candidates[0].id: RoleAnswer(
            role="parte_a", role_confidence=0.9, attribute="nome", attribute_confidence=0.9
        )
    }
    role_suggestions = suggest_kit_fields_by_role(candidates, answers)
    assert role_suggestions == []  # 1 gerador só: nenhum grupo formado
    assert unclustered_candidates(candidates, role_suggestions) == candidates  # mas o candidato não some


def test_candidates_to_members_regroups_by_generator():
    members = [
        MemberFields("g1", "A", (fd("nome", "Nome", "text_short"), fd("cpf", "CPF", "cpf"))),
        MemberFields("g2", "B", (fd("nome", "Nome", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    back = candidates_to_members(candidates)
    by_gid = {m.generator_id: m for m in back}
    assert set(by_gid) == {"g1", "g2"}
    assert by_gid["g1"].generator_name == "A" and len(by_gid["g1"].fields) == 2
    assert by_gid["g2"].generator_name == "B" and len(by_gid["g2"].fields) == 1


def _hybrid(candidates, answers):
    """Mesma orquestração de `kits/service.py::auto_detect` (papel primeiro, resto por similaridade)."""
    role_suggestions = suggest_kit_fields_by_role(candidates, answers)
    leftover = unclustered_candidates(candidates, role_suggestions)
    leftover_suggestions = suggest_kit_fields(candidates_to_members(leftover)) if leftover else []
    return merge_suggestion_lists(role_suggestions, leftover_suggestions)


def test_hybrid_recovers_identical_label_that_classifier_was_unsure_about_on_both_sides():
    """ "Nome completo" é IDÊNTICO nos dois geradores, mas sozinho (sem "do contratante"/"do declarante")
    não dá contexto pro classificador escolher um papel com confiança — a heurística por similaridade,
    aplicada ao que sobrou, resolve o caso óbvio."""
    members = [
        MemberFields("g1", "A", (fd("nome_completo", "Nome completo", "text_short"),)),
        MemberFields("g2", "B", (fd("nome_completo", "Nome completo", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    # classificador "em dúvida" dos dois lados: confiança de papel abaixo do mínimo
    answers = {
        c.id: RoleAnswer(role="parte_a", role_confidence=0.4, attribute="nome", attribute_confidence=0.9)
        for c in candidates
    }
    out = _hybrid(candidates, answers)
    assert len(out) == 1 and set(out[0].mapping) == {"g1", "g2"}


def test_hybrid_recovers_identical_label_with_confidence_straddling_the_cutoff():
    """Bug real encontrado testando contra a API da TypeSafe: os dois "Nome completo" (idênticos) receberam
    confiança em lados OPOSTOS do corte — 0.7 (confiante) e 0.51 (não). Separar cada candidato ISOLADAMENTE
    em "confiante" vs "resto" deixava o de 0.7 sozinho (grupo descartado, < 2 geradores) e o de 0.51 sozinho
    no "resto" (sem par ali também) — os dois desapareciam. `unclustered_candidates` corrige isso: só
    considera "usado" quem entrou de fato num GRUPO de ≥2, então o de 0.7 (órfão) também volta pro resto."""
    members = [
        MemberFields("g1", "A", (fd("nome_completo", "Nome completo", "text_short"),)),
        MemberFields("g2", "B", (fd("nome_completo", "Nome completo", "text_short"),)),
    ]
    candidates = build_role_candidates(members)
    g1_id = next(c.id for c in candidates if c.generator_id == "g1")
    g2_id = next(c.id for c in candidates if c.generator_id == "g2")
    answers = {
        g1_id: RoleAnswer(role="parte_a", role_confidence=0.7, attribute="nome", attribute_confidence=1.0),
        g2_id: RoleAnswer(role="parte_a", role_confidence=0.51, attribute="nome", attribute_confidence=1.0),
    }
    out = _hybrid(candidates, answers)
    assert len(out) == 1 and set(out[0].mapping) == {"g1", "g2"}


def test_merge_suggestion_lists_combines_groups_with_the_same_label_and_type():
    from app.modules.kits.matching import SuggestedKitField

    a = SuggestedKitField(
        name="nome",
        label="Nome",
        type="text_short",
        required=True,
        mask=None,
        example=None,
        mapping={"g1": "nome"},
    )
    b = SuggestedKitField(
        name="nome",
        label="Nome",
        type="text_short",
        required=False,
        mask=None,
        example=None,
        mapping={"g2": "nome"},
    )
    out = merge_suggestion_lists([a], [b])
    assert len(out) == 1 and out[0].mapping == {"g1": "nome", "g2": "nome"} and out[0].required is True


def test_merge_suggestion_lists_drops_groups_left_with_a_single_generator():
    from app.modules.kits.matching import SuggestedKitField

    only_one = SuggestedKitField(
        name="x", label="X", type="text_short", required=False, mask=None, example=None, mapping={"g1": "x"}
    )
    assert merge_suggestion_lists([only_one], []) == []

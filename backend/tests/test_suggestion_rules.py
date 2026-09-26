"""Regras determinísticas novas (ano, mês, numeração de duplicatas) e reforço do provedor local (nome logo
após um rótulo de parte, ex. "CONTRATANTE"). Testes puros — sem banco, sem upload de .docx."""

from __future__ import annotations

from app.adapters.ai.base import AISuggestionRequest, BlockText
from app.adapters.ai.local import LocalHeuristicProvider
from app.modules.fields.normalize import MONTHS
from app.modules.fields.types import role_before
from app.modules.suggestions.rules import MONTH_OPTIONS, Hit, detect_rules
from app.modules.suggestions.service import _number_duplicate_hits

# ---------------------------------------------------------------------------------------------------------
# role_before (helper compartilhado entre rules.py e local.py)


def test_role_before_finds_the_closest_preceding_role_word():
    text = "CONTRATANTE, doravante denominado assim, e CONTRATADA, também denominada assim: "
    assert role_before(text, len(text)) == "contratada"  # o mais próximo, não o primeiro


def test_role_before_returns_none_without_a_role_word_nearby():
    assert role_before("nada relevante aqui: ", 20) is None


def test_role_before_ignores_matches_outside_the_window():
    role = "contratante " + ("x" * 300)
    assert role_before(role, len(role)) is None  # fora da janela de 260 caracteres


# ---------------------------------------------------------------------------------------------------------
# Regra de ANO (4 dígitos 19xx/20xx)


def test_standalone_year_is_suggested_as_ano():
    hits = detect_rules([("body/p1", "Renovação automática a cada ano a partir de 2026.")])
    ano = [h for h in hits if h.name == "ano"]
    assert len(ano) == 1 and ano[0].text == "2026" and ano[0].type == "number"


def test_year_inside_a_short_date_loses_to_the_date_rule():
    hits = detect_rules([("body/p1", "Assinado em 01/10/2026.")])
    names = {h.name for h in hits}
    assert "data" in names and "ano" not in names  # a data (confiança maior) vence a sobreposição


def test_year_inside_a_long_form_date_loses_to_the_date_rule():
    hits = detect_rules([("body/p1", "Assinado em 21 de outubro de 2026.")])
    names = {h.name for h in hits}
    assert "data" in names and "ano" not in names


def test_year_outside_1900_2099_range_is_not_matched():
    hits = detect_rules([("body/p1", "O código do produto é 3026 unidades.")])
    assert not any(h.name == "ano" for h in hits)


# ---------------------------------------------------------------------------------------------------------
# Regra de MÊS (lista suspensa com os 12 meses)


def test_standalone_month_is_suggested_as_select_with_all_twelve_months():
    hits = detect_rules([("body/p1", "O pagamento ocorre todo mês de outubro.")])
    mes = [h for h in hits if h.name == "mes"]
    assert len(mes) == 1
    h = mes[0]
    assert h.type == "select" and h.text.lower() == "outubro"
    assert h.config == {"options": MONTH_OPTIONS}
    assert len(MONTH_OPTIONS) == 12
    assert {o["label"] for o in MONTH_OPTIONS} == {m.capitalize() for m in MONTHS}


def test_month_word_inside_a_long_form_date_loses_to_the_date_rule():
    hits = detect_rules([("body/p1", "Assinado em 21 de outubro de 2026.")])
    names = {h.name for h in hits}
    assert "data" in names and "mes" not in names


def test_month_word_is_case_insensitive():
    hits = detect_rules([("body/p1", "Válido a partir de JANEIRO próximo.")])
    assert any(h.name == "mes" for h in hits)


# ---------------------------------------------------------------------------------------------------------
# Numeração de sugestões duplicadas (valores DIFERENTES do mesmo campo-base)


def _hit(name: str, label: str, text: str, block: str = "body/p1", start: int = 0) -> Hit:
    return Hit(block, start, start + len(text), text, name, label, "cnpj", 0.9, "rule", "")


def test_two_different_cnpjs_get_numbered_labels():
    hits = [
        _hit("cnpj", "CNPJ", "11.222.333/0001-81", start=0),
        _hit("cnpj", "CNPJ", "44.555.666/0001-99", start=30),
    ]
    out = _number_duplicate_hits(hits)
    assert [h.name for h in out] == ["cnpj_1", "cnpj_2"]
    assert [h.label for h in out] == ["CNPJ 1", "CNPJ 2"]


def test_repeated_occurrences_of_the_same_value_are_not_numbered():
    hits = [
        _hit("cnpj", "CNPJ", "11.222.333/0001-81", start=0),
        _hit("cnpj", "CNPJ", "11.222.333/0001-81", start=50),  # mesmo valor, outra ocorrência
    ]
    out = _number_duplicate_hits(hits)
    assert [h.name for h in out] == ["cnpj", "cnpj"]
    assert [h.label for h in out] == ["CNPJ", "CNPJ"]


def test_a_single_value_is_never_numbered():
    hits = [_hit("cnpj", "CNPJ", "11.222.333/0001-81")]
    out = _number_duplicate_hits(hits)
    assert out[0].name == "cnpj" and out[0].label == "CNPJ"


def test_numbering_only_applies_within_the_same_base_name():
    hits = [
        _hit("cnpj", "CNPJ", "11.222.333/0001-81", start=0),
        _hit("cnpj", "CNPJ", "44.555.666/0001-99", start=30),
        _hit("valor", "Valor", "R$ 100,00", start=60),  # base diferente: não entra na contagem do cnpj
    ]
    out = _number_duplicate_hits(hits)
    assert [h.name for h in out] == ["cnpj_1", "cnpj_2", "valor"]


def test_numbering_order_follows_document_position():
    # a ordem de entrada já reflete (block_key, start) — mesma garantia de resolve_overlaps
    hits = [
        _hit("cnpj", "CNPJ", "44.555.666/0001-99", start=0),  # aparece primeiro no documento
        _hit("cnpj", "CNPJ", "11.222.333/0001-81", start=50),
    ]
    out = _number_duplicate_hits(hits)
    assert out[0].text == "44.555.666/0001-99" and out[0].name == "cnpj_1"
    assert out[1].text == "11.222.333/0001-81" and out[1].name == "cnpj_2"


def test_end_to_end_two_cnpjs_via_detect_rules_are_numbered_by_the_service_layer():
    hits = detect_rules(
        [("body/p1", "CNPJ 11.222.333/0001-81 e CNPJ 44.555.666/0001-99 são as partes envolvidas.")]
    )
    out = _number_duplicate_hits(hits)
    cnpjs = [h for h in out if h.name.startswith("cnpj")]
    assert {h.name for h in cnpjs} == {"cnpj_1", "cnpj_2"}
    assert {h.label for h in cnpjs} == {"CNPJ 1", "CNPJ 2"}


# ---------------------------------------------------------------------------------------------------------
# LocalHeuristicProvider: nome relabelado quando um papel aparece logo antes (não só "ROLE:" com dois-pontos)


def _blocks(*texts: str) -> AISuggestionRequest:
    return AISuggestionRequest([BlockText(f"body/p{i}", t, "") for i, t in enumerate(texts)])


def test_local_provider_relabels_a_repeated_name_preceded_by_a_role_word():
    req = _blocks(
        "Pelo presente instrumento, o CONTRATANTE Ricardo Alves de Souza contrata os serviços descritos.",
        "Fica certo que Ricardo Alves de Souza deverá pagar em dia.",
    )
    res = LocalHeuristicProvider().suggest(req)
    names = {s.name for s in res.suggestions}
    assert "contratante" in names and "nome_pessoa" not in names
    contratante = [s for s in res.suggestions if s.name == "contratante"]
    assert all(s.label == "Contratante" for s in contratante)
    assert len(contratante) == 2  # as duas ocorrências recebem o MESMO papel (achado na primeira)


def test_local_provider_falls_back_to_generic_name_without_a_nearby_role_word():
    req = _blocks(
        "Maria Fernanda Costa Lima assina este documento.",
        "Maria Fernanda Costa Lima também rubrica todas as páginas.",
    )
    res = LocalHeuristicProvider().suggest(req)
    names = {s.name for s in res.suggestions}
    assert "nome_pessoa" in names
    assert all(s.label == "Nome" for s in res.suggestions if s.name == "nome_pessoa")


def test_local_provider_does_not_relabel_a_name_that_only_appears_once():
    req = _blocks("Pelo CONTRATANTE, assina Fulano de Tal Pereira, uma única vez neste documento.")
    res = LocalHeuristicProvider().suggest(req)
    assert not any(s.text == "Fulano de Tal Pereira" for s in res.suggestions)  # <2 ocorrências: ignorado

"""“Cole aqui e a gente descobre o modelo”: tabela colada → modelo + mapeamento de colunas."""

from __future__ import annotations

import uuid

import pytest

from app.modules.fields.types import FieldDef
from app.modules.generation import identify
from app.modules.kits.matching import RoleAnswer, RoleCandidate
from tests.flows import build_generator


def fd(name: str, label: str, type_: str = "text_short", **kw) -> FieldDef:
    return FieldDef(id=name, name=name, label=label, type=type_, **kw)


CONTRACT = [
    fd("nome_do_contratante", "Nome do contratante", required=True),
    fd("cpf_do_contratante", "CPF do contratante", "cpf", required=True),
    fd("valor_mensal", "Valor mensal", "currency", required=True),
    fd("data_de_inicio", "Data de início", "date"),
]


def _by_header(matches: list[identify.ColumnMatch]) -> dict[str, tuple[str, str]]:
    return {m.header: (m.field, m.source) for m in matches}


def test_matches_by_name_spelling_containment_and_content():
    headers = ["Nome do contratante *", "Valor mensa", "Início", "Documento"]
    samples = [["Ana"], ["1.200,00"], ["01/02/2027"], ["529.982.247-25"]]
    got = _by_header(identify.match_columns(headers, samples, CONTRACT))
    assert got["Nome do contratante *"] == ("nome_do_contratante", "nome")  # marca de obrigatório ignorada
    assert got["Valor mensa"] == ("valor_mensal", "parecido")  # erro de digitação
    assert got["Início"] == ("data_de_inicio", "parecido")  # contido em "Data de início"
    assert got["Documento"] == ("cpf_do_contratante", "conteudo")  # coluna de CPFs → o único campo de CPF


def test_values_of_the_wrong_type_weaken_a_name_match():
    # "CPF" parece o campo de CPF, mas a coluna tem datas: confiança cai abaixo do corte
    got = identify.match_columns(["CPF"], [["01/02/2027", "03/04/2027"]], CONTRACT)
    assert got == []


def test_ambiguous_short_header_is_not_trusted_blindly():
    defs = [fd("nome_do_locador", "Nome do locador"), fd("nome_do_locatario", "Nome do locatário")]
    got = identify.match_columns(["Nome"], [["Ana"]], defs)
    assert len(got) == 1 and got[0].confidence < 0.6  # serve aos dois: casa, mas com confiança baixa


def test_score_exact_only_when_every_column_and_required_field_match():
    exact = identify.candidate_for(
        "g", "Contrato", CONTRACT, ["Nome do contratante", "CPF do contratante", "Valor mensal"], [[], [], []]
    )
    assert exact.exact and exact.score > 0.8 and exact.missing_required == []
    partial = identify.candidate_for(
        "g", "Contrato", CONTRACT, ["Nome do contratante", "Observação"], [[], []]
    )
    assert not partial.exact
    assert partial.unmatched_columns == ["Observação"]
    assert set(partial.missing_required) == {"CPF do contratante", "Valor mensal"}


# ------------------------------------------------------------------ API


def _paste(api, headers: list[str], rows: list[list[str]] | None = None) -> dict:
    r = api.post("/batch/identify", json={"headers": headers, "rows": rows or []})
    assert r.status_code == 200, r.text
    return r.json()


def test_identifies_the_right_model_among_several(api, demo_docx):
    api.register()
    contract = build_generator(api, demo_docx, name="Contrato de serviços")["id"]
    receipt = api.post("/samples/generator").json()["id"]  # outro modelo pronto no mesmo espaço
    assert receipt != contract

    headers = [
        "Nome do contratante",
        "CPF do contratante",
        "CNPJ da contratada",
        "Tipo de serviço",
        "Valor mensal",
        "Data de início",
        "Renovação automática",
    ]
    rows = [
        [
            "Maria Souza",
            "529.982.247-25",
            "11.222.333/0001-81",
            "Suporte técnico mensal",
            "1.234,50",
            "15/11/2026",
            "Não",
        ]
    ]
    out = _paste(api, headers, rows)
    assert out["status"] == "exact"
    best = out["candidates"][0]
    assert best["generator_id"] == contract and best["exact"] is True
    assert [m["field"] for m in best["mapping"]] == [
        "nome_do_contratante",
        "cpf_do_contratante",
        "cnpj_da_contratada",
        "tipo_de_servico",
        "valor_mensal",
        "data_de_inicio",
        "renovacao_automatica",
    ]


def test_loose_headers_give_a_probable_match_and_say_what_is_missing(api, demo_docx):
    api.register()
    contract = build_generator(api, demo_docx, name="Contrato de serviços")["id"]
    out = _paste(
        api, ["Contratante", "CPF", "Valor", "Início"], [["Ana", "529.982.247-25", "900,00", "01/02/2027"]]
    )
    assert out["status"] in ("probable", "weak")
    best = out["candidates"][0]
    assert best["generator_id"] == contract and best["exact"] is False
    assert {m["field"] for m in best["mapping"]} >= {"cpf_do_contratante", "valor_mensal", "data_de_inicio"}
    assert "Tipo de serviço" in best["missing_required"]


def test_unrelated_table_finds_nothing(api, demo_docx):
    api.register()
    build_generator(api, demo_docx)
    out = _paste(api, ["Produto", "Quantidade", "Estoque"], [["Parafuso", "10", "3"]])
    assert out == {
        "status": "none",
        "semantic": False,
        "columns": ["Produto", "Quantidade", "Estoque"],
        "candidates": [],
    }


def test_semantic_classifier_suggests_when_there_is_no_exact_match(
    api, demo_docx, monkeypatch: pytest.MonkeyPatch
):
    """Sem nome parecido ("Locatário" × "Nome do contratante"), o classificador de papéis (Jev) casa os dois
    pelo papel — e o resultado vem como sugestão ("semantico"), nunca como correspondência exata."""
    api.register()
    contract = build_generator(api, demo_docx)["id"]

    class FakeClassifier:
        def classify(self, candidates: list[RoleCandidate]) -> dict[str, RoleAnswer]:
            out = {}
            for c in candidates:
                if c.field.label in ("Locatário", "Nome do contratante"):
                    out[c.id] = RoleAnswer("contratante", 0.9, "nome", 0.9)
            return out

    monkeypatch.setattr("app.adapters.ai.get_role_classifier", lambda: FakeClassifier())
    out = _paste(api, ["Locatário", "CPF do contratante"], [["Ana", "529.982.247-25"]])
    assert out["semantic"] is True
    best = out["candidates"][0]
    assert best["generator_id"] == contract and best["exact"] is False
    by_header = {m["header"]: (m["field"], m["source"]) for m in best["mapping"]}
    assert by_header["Locatário"] == ("nome_do_contratante", "semantico")
    assert by_header["CPF do contratante"] == ("cpf_do_contratante", "nome")


def test_chosen_model_returns_its_mapping_even_when_weak(api, demo_docx):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    body = {"headers": ["Produto", "CPF"], "rows": [["X", "529.982.247-25"]], "generator_id": gid}
    out = _paste_raw(api, body)
    assert out["candidates"][0]["generator_id"] == gid
    assert [m["field"] for m in out["candidates"][0]["mapping"]] == ["cpf_do_contratante"]
    assert out["candidates"][0]["unmatched_columns"] == ["Produto"]
    missing = api.post("/batch/identify", json={"headers": ["A"], "generator_id": str(uuid.uuid4())})
    assert missing.status_code == 404


def _paste_raw(api, body: dict) -> dict:
    r = api.post("/batch/identify", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_identify_is_scoped_to_the_workspace(api, api2, demo_docx):
    api.register()
    build_generator(api, demo_docx)
    api2.register()
    out = _paste(api2, ["Nome do contratante", "CPF do contratante"])
    assert out["candidates"] == []

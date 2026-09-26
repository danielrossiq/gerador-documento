"""Validações de CPF/CNPJ, normalização por tipo e nomes técnicos. Usa vetores compartilhados com o frontend."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.modules.fields.normalize import format_value, normalize_value, validate_row
from app.modules.fields.types import FieldDef, OptionDef, to_snake_case, unique_name
from app.modules.fields.validators import is_valid_cnpj, is_valid_cpf, normalize_phone

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "field-vectors.json").read_text(encoding="utf-8")
)["cases"]


def _fd(case: dict) -> FieldDef:
    return FieldDef(
        id="x",
        name="campo",
        label="Campo",
        type=case["type"],
        required=bool(case.get("required")),
        options=tuple(OptionDef(o["label"], o["value"]) for o in case.get("options", [])),
        config=case.get("config") or {},
    )


@pytest.mark.parametrize("case", VECTORS, ids=[f"{c['type']}:{c['input']!r}"[:60] for c in VECTORS])
def test_shared_vectors(case):
    fd = _fd(case)
    value, err = normalize_value(fd, case["input"])
    assert err == case["error"], f"erro esperado {case['error']!r}, obtido {err!r}"
    assert value == case["canonical"]
    if case["error"] is None:
        assert format_value(fd, value) == case["formatted"]


def test_excel_serial_matches_iso_date():
    assert (date(2026, 9, 21) - date(1899, 12, 30)).days == 46286


@pytest.mark.parametrize(
    "cpf,ok",
    [
        ("123.456.789-09", True),
        ("529.982.247-25", True),
        ("000.000.000-00", False),
        ("111.111.111-11", False),
        ("123.456.789-00", False),
        ("1234567890", False),
        ("abc", False),
    ],
)
def test_cpf(cpf, ok):
    assert is_valid_cpf(cpf) is ok


@pytest.mark.parametrize(
    "cnpj,ok",
    [
        ("11.222.333/0001-81", True),
        ("11444777000161", True),
        ("00.000.000/0000-00", False),
        ("11.222.333/0001-82", False),
        ("12ABC34501DE35", True),
        ("12ABC34501DE36", False),
        ("123", False),
    ],
)
def test_cnpj_numeric_and_alphanumeric(cnpj, ok):
    assert is_valid_cnpj(cnpj) is ok


def test_phone_rules():
    assert normalize_phone("(11) 98765-4321") == "11987654321"
    assert normalize_phone("11 3456-7890") == "1134567890"
    assert normalize_phone("(11) 88765-4321") is None  # celular deve começar com 9
    assert normalize_phone("(23) 91234-5678") is None  # DDD inexistente


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Nome do contratante", "nome_do_contratante"),
        ("  Valor (R$) ", "valor_r"),
        ("Endereço – CEP", "endereco_cep"),
        ("123 teste", "campo_123_teste"),
        ("###", "campo"),
    ],
)
def test_snake_case(label, expected):
    assert to_snake_case(label) == expected


def test_unique_name_and_reserved():
    assert unique_name("nome", ["nome", "nome_2"]) == "nome_3"
    assert unique_name("linha", []) == "linha_2"  # nomes reservados dos tokens de arquivo


def test_validate_row_applies_defaults_and_reports_errors():
    defs = [
        FieldDef("1", "nome", "Nome", "text_short", required=True),
        FieldDef("2", "valor", "Valor", "currency", default="100"),
        FieldDef("3", "cpf", "CPF", "cpf"),
    ]
    res = validate_row(defs, {"nome": "", "cpf": "111.111.111-11"})
    assert res.errors == {"nome": "Campo obrigatório.", "cpf": "CPF inválido."}
    assert res.values["valor"] == "100.00"
    assert not res.valid


def test_text_mask_validation():
    fd = FieldDef("1", "proc", "Processo", "text_short", mask="####-AA")
    assert normalize_value(fd, "1234-AB") == ("1234-AB", None)
    assert normalize_value(fd, "12345")[1].startswith("Formato inválido")

"""Classificador de papéis via TypeSafe/Jev (adaptador HTTP) e sua integração com o auto-detect de kits —
ver docs/DECISIONS.md D24. Estes testes cobrem só o adaptador (requisição/resposta/retry/erros); o
agrupamento por papel em si é testado em test_kit_matching.py (puro, sem HTTP)."""

from __future__ import annotations

import httpx
import pytest

from app.adapters.ai.typesafe import (
    ATTR_PREFIX,
    ROLE_PREFIX,
    RoleClassifierUnavailable,
    TypeSafeRoleClassifier,
)
from app.modules.fields.types import FieldDef
from app.modules.kits.matching import MemberFields, RoleCandidate, build_role_candidates


def fd(name: str, label: str, type_: str, **kw) -> FieldDef:
    return FieldDef(id=name, name=name, label=label, type=type_, **kw)


def _classifier(handler, **kw) -> TypeSafeRoleClassifier:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TypeSafeRoleClassifier(
        "k", "https://ia.exemplo", "jev-latest", 5, kw.pop("retries", 2), sleep=lambda s: None, client=client
    )


def _candidates() -> list[RoleCandidate]:
    members = [
        MemberFields(
            "g1",
            "Contrato A",
            (fd("nome_contratante", "Nome do contratante", "text_short"), fd("cpf", "CPF", "cpf")),
        ),
        MemberFields("g2", "Contrato B", (fd("nome_completo", "Nome completo", "text_short"),)),
    ]
    return build_role_candidates(members)


def _good_response(candidates: list[RoleCandidate]) -> dict:
    answers = {}
    for c in candidates:
        answers[f"{ROLE_PREFIX}{c.id}"] = {
            "type": "choice",
            "choice": "parte_a",
            "probabilities": {"parte_a": 0.8, "parte_b": 0.1, "terceiro": 0.05, "nao_e_parte": 0.05},
            "confidence": 0.8,
        }
        if c.needs_attribute:
            answers[f"{ATTR_PREFIX}{c.id}"] = {
                "type": "choice",
                "choice": "nome",
                "probabilities": {
                    "nome": 0.9,
                    "endereco": 0.05,
                    "cargo_profissao": 0.02,
                    "objeto": 0.02,
                    "outro": 0.01,
                },
                "confidence": 0.9,
            }
    return {"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_classifier_sends_bearer_auth_and_batches_all_candidates_in_one_call():
    candidates = _candidates()
    calls: list[dict] = []

    def handler(req):
        import json

        calls.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json=_good_response(candidates))

    out = _classifier(handler).classify(candidates)
    assert len(calls) == 1  # uma chamada só, mesmo com vários campos candidatos
    body = calls[0]
    assert body["model"] == "jev-latest"
    # um Choice de papel por candidato + um de atributo só para os de texto livre (nome_contratante, nome_completo)
    text_candidates = [c for c in candidates if c.needs_attribute]
    assert len(body["questions"]) == len(candidates) + len(text_candidates)
    assert len(out) == len(candidates)
    assert all(a.role == "parte_a" for a in out.values())


def test_classifier_parses_attribute_only_for_text_fields():
    candidates = _candidates()
    out = _classifier(lambda req: httpx.Response(200, json=_good_response(candidates))).classify(candidates)
    cpf_candidate = next(c for c in candidates if c.field.type == "cpf")
    text_candidate = next(c for c in candidates if c.needs_attribute)
    assert out[cpf_candidate.id].attribute is None  # cpf não precisa de atributo
    assert out[text_candidate.id].attribute == "nome"
    assert out[text_candidate.id].attribute_confidence == 0.9


def test_classifier_drops_answers_outside_the_known_vocabulary():
    candidates = _candidates()
    resp = _good_response(candidates)
    # simula uma resposta fora do vocabulário esperado (não deveria acontecer, mas a validação não pode confiar cego)
    a_key = next(k for k in resp["answers"] if k.startswith(ROLE_PREFIX))
    resp["answers"][a_key]["choice"] = "papel_inventado"
    out = _classifier(lambda req: httpx.Response(200, json=resp)).classify(candidates)
    dropped_id = a_key[len(ROLE_PREFIX) :]
    assert dropped_id not in out


def test_classifier_retries_transient_errors_then_succeeds():
    candidates = _candidates()
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=_good_response(candidates))

    assert _classifier(handler).classify(candidates) and len(calls) == 3


def test_classifier_gives_up_after_limited_retries():
    candidates = _candidates()
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(529)  # "service overloaded" (documentado pela TypeSafe)

    with pytest.raises(RoleClassifierUnavailable) as exc:
        _classifier(handler, retries=2).classify(candidates)
    assert exc.value.code == "TYPESAFE_UNAVAILABLE" and len(calls) == 3


def test_classifier_auth_error_does_not_retry():
    candidates = _candidates()
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(RoleClassifierUnavailable) as exc:
        _classifier(handler).classify(candidates)
    assert exc.value.code == "TYPESAFE_AUTH_FAILED" and len(calls) == 1


def test_classifier_timeout_raises_unavailable():
    candidates = _candidates()

    def timeout(req):
        raise httpx.ReadTimeout("lento")

    with pytest.raises(RoleClassifierUnavailable) as exc:
        _classifier(timeout, retries=0).classify(candidates)
    assert exc.value.code == "TYPESAFE_TIMEOUT"


def test_classifier_rejects_malformed_response():
    candidates = _candidates()
    with pytest.raises(RoleClassifierUnavailable) as exc:
        _classifier(lambda req: httpx.Response(200, json={"model": "x"})).classify(candidates)
    assert exc.value.code == "TYPESAFE_INVALID_RESPONSE"


def test_classifier_with_no_candidates_makes_no_request():
    calls = []
    out = _classifier(lambda req: calls.append(1) or httpx.Response(200, json={"answers": {}})).classify([])
    assert out == {} and calls == []


def test_classifier_request_only_carries_label_type_and_generator_name():
    """Privacidade: o corpo enviado à TypeSafe só pode ter rótulo/tipo/nome do gerador — nunca um valor
    preenchido pelo usuário (que neste ponto do fluxo — o kit ainda nem foi gerado — nem existe)."""
    candidates = _candidates()
    sent = {}

    def handler(req):
        import json

        sent["body"] = json.loads(req.content)
        return httpx.Response(200, json=_good_response(candidates))

    _classifier(handler).classify(candidates)
    blob = str(sent["body"])
    for c in candidates:
        assert c.field.label in blob and c.generator_name in blob
    assert "529.982.247-25" not in blob and "Maria" not in blob  # nenhum valor de exemplo, só metadado

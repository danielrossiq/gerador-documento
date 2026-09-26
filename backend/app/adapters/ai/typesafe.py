"""Classificação semântica de papéis para o auto-detect de kits, via a API da TypeSafe.ai (modelo "Jev").

Só entra em jogo se `TYPESAFE_API_KEY` estiver configurada; qualquer falha (rede, timeout, credencial,
resposta fora do formato) levanta `RoleClassifierUnavailable` e quem chama cai de volta na heurística local
por similaridade de rótulo (`app.modules.kits.matching.suggest_kit_fields`) — ver docs/DECISIONS.md D24.
Privacidade: só rótulo, tipo e nome do gerador são enviados — nunca valores preenchidos pelo usuário.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.modules.kits.matching import ATTRIBUTE_CRITERIA, ROLE_CRITERIA, RoleAnswer, RoleCandidate

log = get_logger(__name__)

ROLE_PREFIX = "role::"
ATTR_PREFIX = "attr::"


class RoleClassifierUnavailable(Exception):
    """Classificador indisponível (rede, quota, timeout, credencial). O auto-detect segue com a heurística local."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TypeSafeRoleClassifier:
    name = "typesafe"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        max_retries: int = 2,
        sleep: Any = time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._client = client

    def _build_state(self, candidates: list[RoleCandidate]) -> str:
        lines = [
            "Campos extraídos de documentos diferentes que podem compartilhar variáveis. Para cada um, "
            "o documento de origem, o rótulo e o tipo:"
        ]
        for c in candidates:
            lines.append(
                f'[{c.id}] Documento: "{c.generator_name}" · Campo: "{c.field.label}" · Tipo: {c.field.type}'
            )
        return "\n".join(lines)

    def _build_questions(self, candidates: list[RoleCandidate]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {}
        for c in candidates:
            questions[f"{ROLE_PREFIX}{c.id}"] = {
                "type": "choice",
                "instructions": f"Qual é o papel do campo [{c.id}] na lista acima?",
                "criteria": ROLE_CRITERIA,
            }
            if c.needs_attribute:
                questions[f"{ATTR_PREFIX}{c.id}"] = {
                    "type": "choice",
                    "instructions": f"Que tipo de informação é o campo [{c.id}] na lista acima?",
                    "criteria": ATTRIBUTE_CRITERIA,
                }
        return questions

    def classify(self, candidates: list[RoleCandidate]) -> dict[str, RoleAnswer]:
        if not candidates:
            return {}
        body = {
            "state": self._build_state(candidates),
            "model": self.model,
            "questions": self._build_questions(candidates),
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        last_error = "TYPESAFE_UNAVAILABLE"
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.post(
                        f"{self.base_url}/v1/systemone", json=body, headers=headers, timeout=self.timeout
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    last_error = "TYPESAFE_TIMEOUT"
                else:
                    if resp.status_code == 200:
                        return self._parse(resp.json(), candidates)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_error = (
                            "TYPESAFE_RATE_LIMITED" if resp.status_code == 429 else "TYPESAFE_UNAVAILABLE"
                        )
                    elif resp.status_code == 401:
                        raise RoleClassifierUnavailable(
                            "TYPESAFE_AUTH_FAILED", "Credencial da TypeSafe inválida."
                        )
                    else:
                        raise RoleClassifierUnavailable(
                            "TYPESAFE_REQUEST_REJECTED",
                            f"A TypeSafe recusou a requisição (HTTP {resp.status_code}).",
                        )
                if attempt < self.max_retries:
                    self._sleep(min(0.5 * (2**attempt), 4.0))
        finally:
            if self._client is None:
                client.close()
        raise RoleClassifierUnavailable(last_error, "Classificador de papéis indisponível no momento.")

    def _parse(self, payload: dict[str, Any], candidates: list[RoleCandidate]) -> dict[str, RoleAnswer]:
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise RoleClassifierUnavailable(
                "TYPESAFE_INVALID_RESPONSE", "Resposta da TypeSafe fora do formato esperado."
            )
        out: dict[str, RoleAnswer] = {}
        for c in candidates:
            role_ans = answers.get(f"{ROLE_PREFIX}{c.id}") or {}
            role = role_ans.get("choice")
            role_conf = role_ans.get("confidence")
            if (
                not isinstance(role, str)
                or role not in ROLE_CRITERIA
                or not isinstance(role_conf, int | float)
            ):
                continue
            attribute: str | None = None
            attr_conf: float | None = None
            if c.needs_attribute:
                attr_ans = answers.get(f"{ATTR_PREFIX}{c.id}") or {}
                raw_attr = attr_ans.get("choice")
                raw_conf = attr_ans.get("confidence")
                if isinstance(raw_attr, str) and raw_attr in ATTRIBUTE_CRITERIA:
                    attribute = raw_attr
                    attr_conf = float(raw_conf) if isinstance(raw_conf, int | float) else None
            out[c.id] = RoleAnswer(
                role=role,
                role_confidence=float(role_conf),
                attribute=attribute,
                attribute_confidence=attr_conf,
            )
        log.info(
            "kit_classificacao_papeis",
            extra={"provider": self.name, "n_candidates": len(candidates), "n_answered": len(out)},
        )
        return out

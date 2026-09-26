"""Provedor de IA via API Messages (URL, modelo e chave por variáveis de ambiente).

Privacidade: o conteúdo do documento só é enviado durante a *análise/reanálise* do modelo (nunca na
geração). Nada do conteúdo é registrado em log; guardamos só contagens (caracteres, tokens, duração).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.adapters.ai.base import (
    AISuggestionRequest,
    AISuggestionResult,
    AIUnavailable,
    RawSuggestion,
)
from app.core.logging import get_logger
from app.modules.fields.types import FIELD_TYPES

log = get_logger(__name__)

SYSTEM_PROMPT = f"""Você ajuda a transformar documentos repetitivos (contratos, declarações, propostas, formulários de RH)
em modelos com campos variáveis. Receberá blocos numerados de um documento em português do Brasil.
Sugira APENAS trechos que tendem a mudar de um documento para outro: nomes de pessoas e empresas, documentos
(CPF, CNPJ), valores, datas, endereços, cargos, prazos, objeto/serviço, opções Sim/Não.
NÃO sugira texto jurídico fixo, títulos ou cláusulas padrão. NÃO dê aconselhamento jurídico.
Responda SOMENTE com JSON válido no formato:
{{"suggestions":[{{"block":"<chave do bloco>","text":"<trecho exato, copiado do bloco>","name":"<snake_case>",
"label":"<rótulo legível>","type":"<um de: {", ".join(FIELD_TYPES)}>","confidence":<0 a 1>,"reason":"<curto>"}}]}}
O campo "text" deve existir literalmente dentro do bloco indicado."""


class AnthropicMessagesProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        max_retries: int,
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

    def _build_prompt(self, request: AISuggestionRequest) -> tuple[str, int, bool]:
        parts: list[str] = []
        used = 0
        truncated = False
        for b in request.blocks:
            if not b.text.strip():
                continue
            chunk = f"[{b.key}] ({b.location}) {b.text}"
            if used + len(chunk) > request.max_chars:
                truncated = True
                break
            parts.append(chunk)
            used += len(chunk)
        return "\n".join(parts), used, truncated

    def suggest(self, request: AISuggestionRequest) -> AISuggestionResult:
        prompt, chars, truncated = self._build_prompt(request)
        if not prompt:
            return AISuggestionResult([], self.name, self.model, 0, 0, 0, 0, False)
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        started = time.monotonic()
        last_error = "AI_UNAVAILABLE"
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.post(
                        f"{self.base_url}/v1/messages", json=body, headers=headers, timeout=self.timeout
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    last_error = "AI_TIMEOUT"
                else:
                    if resp.status_code == 200:
                        return self._parse(resp.json(), chars, truncated, started)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_error = "AI_RATE_LIMITED" if resp.status_code == 429 else "AI_UNAVAILABLE"
                    elif resp.status_code in (401, 403):
                        raise AIUnavailable("AI_AUTH_FAILED", "Credencial da IA inválida ou sem permissão.")
                    else:
                        raise AIUnavailable(
                            "AI_REQUEST_REJECTED", f"A IA recusou a requisição (HTTP {resp.status_code})."
                        )
                if attempt < self.max_retries:
                    self._sleep(min(0.5 * (2**attempt), 4.0))
        finally:
            if self._client is None:
                client.close()
        raise AIUnavailable(last_error, "Serviço de IA indisponível no momento.")

    def _parse(
        self, payload: dict[str, Any], chars: int, truncated: bool, started: float
    ) -> AISuggestionResult:
        text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        try:
            raw = json.loads(text)
            items = raw.get("suggestions", []) if isinstance(raw, dict) else []
        except json.JSONDecodeError as exc:
            raise AIUnavailable(
                "AI_INVALID_RESPONSE", "A IA devolveu uma resposta que não é JSON válido."
            ) from exc
        valid: list[RawSuggestion] = []
        dropped = 0
        for item in items:
            try:
                valid.append(RawSuggestion.model_validate(item))
            except ValidationError:
                dropped += 1
        usage = payload.get("usage") or {}
        log.info(
            "ia_analise",
            extra={"provider": self.name, "chars": chars, "n_valid": len(valid), "n_dropped": dropped},
        )
        result = AISuggestionResult(
            valid,
            self.name,
            self.model,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            chars,
            int((time.monotonic() - started) * 1000),
            truncated,
        )
        if dropped:
            result.warnings.append(
                f"{dropped} sugestão(ões) da IA foram descartadas por não seguirem o formato."
            )
        if truncated:
            result.warnings.append("O documento é longo: só o início foi analisado pela IA.")
        return result

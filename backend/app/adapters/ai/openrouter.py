"""IA via OpenRouter (API compatível com OpenAI): um cliente de chat com saída JSON validada por schema.

Privacidade e custo, em toda chamada:
- `provider.data_collection = "deny"`: a OpenRouter só encaminha para provedores que não guardam nem usam os
  dados para treinamento;
- `require_parameters = true`: só provedores que respeitam o `response_format` (JSON com schema estrito);
- `usage.include = true`: a resposta traz o custo real em US$, gravado na razão de custo (app.modules.ai_budget).
Nada do conteúdo vai para log; só modelo, contagens, duração e custo.

A chave vem de OPENROUTER_API_KEY ou do arquivo em OPENROUTER_KEY_FILE (ex.: segredo do Docker montado em
/run/secrets). Nunca do repositório, nunca em log.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.adapters.ai.base import AISuggestionRequest, AISuggestionResult, AIUnavailable, RawSuggestion
from app.core.logging import get_logger
from app.modules.fields.types import FIELD_TYPES

log = get_logger(__name__)

KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_-]{20,200}$")


def read_openrouter_key(api_key: str | None, key_file: str | None) -> str | None:
    """Chave da variável de ambiente ou do arquivo (uma linha, prefixo sk-or-). Inválida → None."""
    key = (api_key or "").strip()
    if not key and key_file:
        try:
            path = Path(key_file)
            if path.is_file() and path.stat().st_size <= 1024:
                key = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            key = ""
    return key if KEY_RE.match(key) else None


@dataclass
class ChatResult:
    data: dict[str, Any]
    model: str
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    duration_ms: int


class OpenRouterChat:
    """Uma chamada = um pedido com resposta JSON no schema dado. Erros viram AIUnavailable (código estável)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 45.0,
        max_retries: int = 3,
        referer: str = "https://minuta.app",
        sleep: Any = time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.referer = referer
        self._sleep = sleep
        self._client = client

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> ChatResult:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # sem "temperature": vários modelos (de raciocínio) não aceitam, e com require_parameters a OpenRouter
            # ficaria sem provedor (404). O formato já vem garantido pelo schema estrito.
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "provider": {"data_collection": "deny", "require_parameters": True},
            "usage": {"include": True},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.referer,
            "X-Title": "Minuta",
        }
        started = time.monotonic()
        last = "AI_UNAVAILABLE"
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
                except (httpx.TimeoutException, httpx.TransportError):
                    last = "AI_TIMEOUT"
                else:
                    if resp.status_code == 200:
                        return self._parse(resp.json(), model, started)
                    if resp.status_code in (401, 403):
                        raise AIUnavailable("AI_AUTH_FAILED", "Credencial da IA inválida ou sem permissão.")
                    if resp.status_code == 402:
                        raise AIUnavailable("AI_NO_CREDIT", "A conta de IA está sem crédito.")
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last = "AI_RATE_LIMITED" if resp.status_code == 429 else "AI_UNAVAILABLE"
                    else:
                        detail = ""
                        with contextlib.suppress(ValueError):
                            detail = str((resp.json().get("error") or {}).get("message") or "")[:160]
                        log.warning("ia_recusada", extra={"model": model, "status": resp.status_code, "detail": detail})
                        raise AIUnavailable("AI_REQUEST_REJECTED", f"A IA recusou a requisição (HTTP {resp.status_code}).")
                if attempt < self.max_retries:
                    self._sleep(min(2.0 * (2**attempt), 10.0))
        finally:
            if self._client is None:
                client.close()
        raise AIUnavailable(last, "Serviço de IA indisponível no momento.")

    @staticmethod
    def _parse(payload: dict[str, Any], model: str, started: float) -> ChatResult:
        try:
            choice = payload["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable("AI_INVALID_RESPONSE", "A IA devolveu uma resposta vazia.") from exc
        if choice.get("finish_reason") == "length":
            log.warning("ia_cortada", extra={"model": model, "tokens_out": (payload.get("usage") or {}).get("completion_tokens")})
            raise AIUnavailable("AI_TRUNCATED", "A resposta da IA veio incompleta (documento longo demais para uma chamada).")
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIUnavailable("AI_INVALID_RESPONSE", "A IA devolveu uma resposta que não é JSON válido.") from exc
        if not isinstance(data, dict):
            raise AIUnavailable("AI_INVALID_RESPONSE", "A IA devolveu um JSON fora do formato.")
        usage = payload.get("usage") or {}
        cost = usage.get("cost")
        return ChatResult(
            data=data,
            model=str(payload.get("model") or model),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            cost_usd=float(cost) if cost is not None else None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


# ---------------------------------------------------------------------------------------------- campos do modelo

FIELDS_SYSTEM = f"""Você transforma documentos repetitivos de escritórios brasileiros (contratos, procurações, recibos,
declarações, termos, propostas, documentos de RH) em MODELOS com campos variáveis.

Você recebe os parágrafos do documento, cada um com uma chave entre colchetes. Marque TODO trecho que muda de um
cliente/caso para outro:
- nomes de pessoas e empresas de cada parte (contratante, contratada, locador, locatário, outorgante, advogado,
  empregado, empregador, devedor, credor, declarante…) e de representantes;
- qualificação: nacionalidade, estado civil, profissão, RG, CPF, CNPJ, OAB, e-mail, telefone;
- endereços completos, bairro, CEP e a CIDADE de assinatura (ex.: "São Paulo" em "São Paulo, 3 de março de 2027");
- datas, valores, percentuais, quantidades, prazos (número de meses/anos/dias), número de parcelas, dia de vencimento;
- objeto/serviço, nome de projeto, número de processo, ação, parte contrária, mês de referência, forma de pagamento,
  índice de reajuste, garantia, foro, jornada, cargo, matrícula.
NÃO marque texto jurídico fixo, títulos, rótulos ("CONTRATANTE:", "CPF nº") nem palavras que nunca mudam.

Regras do trecho ("text"):
- copie EXATAMENTE como está no parágrafo (mesmas maiúsculas, acentos e pontuação) e só a parte variável:
  "123.456.789-09" e não "CPF 123.456.789-09"; "São Paulo" e não "São Paulo, 3";
- valor com extenso entre parênteses: marque só o valor ("R$ 5.000,00");
- o mesmo dado repetido em vários parágrafos: uma entrada por ocorrência, com o MESMO "name";
- dados diferentes nunca compartilham "name" (o nome do locador e o do locatário são campos distintos).

"name": snake_case pelo papel ("nome_locatario", "cpf_contratante", "cidade", "valor_aluguel", "prazo_meses").
"label": rótulo curto em português ("Nome do locatário"). "type": um de {", ".join(FIELD_TYPES)} — text_short para
nomes, endereços e textos curtos; text_long para descrições longas; number para quantidades e prazos; currency para
valores em R$; date para datas; select para opções de uma lista conhecida (estado civil, mês, forma de pagamento).
"confidence": 0 a 1. "reason": até 8 palavras."""

FIELDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["block", "text", "name", "label", "type", "confidence", "reason"],
                "properties": {
                    "block": {"type": "string"},
                    "text": {"type": "string"},
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "type": {"type": "string", "enum": list(FIELD_TYPES)},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def build_blocks_prompt(request: AISuggestionRequest) -> tuple[str, int, bool]:
    parts: list[str] = []
    used, truncated = 0, False
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


def max_output_tokens(chars: int) -> int:
    """Teto de saída proporcional ao documento (cada campo ~45 tokens; documento curto ~10–20 campos).

    Inclui folga para o "raciocínio" dos modelos que pensam antes de responder (Haiku, GPT-5…): esses tokens
    saem do mesmo teto e, sem folga, o JSON era cortado no meio. Só se paga o que for usado.
    """
    return int(min(8000, max(4000, chars / 4 + 2500)))


class OpenRouterFieldProvider:
    """Sugestão de campos (análise do modelo enviado) por um modelo da OpenRouter."""

    name = "openrouter"

    def __init__(self, chat: OpenRouterChat, model: str) -> None:
        self.chat = chat
        self.model = model
        self.last_cost_usd: float | None = None

    def suggest(self, request: AISuggestionRequest) -> AISuggestionResult:
        prompt, chars, truncated = build_blocks_prompt(request)
        if not prompt:
            return AISuggestionResult([], self.name, self.model, 0, 0, 0, 0, False)
        res = self.chat.complete(
            model=self.model,
            system=FIELDS_SYSTEM,
            user=prompt,
            schema_name="campos",
            schema=FIELDS_SCHEMA,
            max_tokens=max_output_tokens(chars),
        )
        self.last_cost_usd = res.cost_usd
        valid: list[RawSuggestion] = []
        dropped = 0
        for item in res.data.get("suggestions") or []:
            try:
                valid.append(RawSuggestion.model_validate(item))
            except ValidationError:
                dropped += 1
        log.info("ia_campos", extra={"provider": self.name, "model": res.model, "chars": chars, "n_valid": len(valid), "n_dropped": dropped})
        out = AISuggestionResult(valid, self.name, res.model, res.tokens_in, res.tokens_out, chars, res.duration_ms, truncated)
        if dropped:
            out.warnings.append(f"{dropped} sugestão(ões) da IA foram descartadas por não seguirem o formato.")
        if truncated:
            out.warnings.append("O documento é longo: só o início foi analisado pela IA.")
        return out

"""Provedor LOCAL de sugestões (heurísticas em português). Usado quando não há chave de IA.

IMPORTANTE: isto NÃO é um modelo de linguagem. São regras simples (rótulos como "CONTRATANTE:",
nomes próprios repetidos, razão social com Ltda./S.A., cargo, prazo, endereço) com confiança
moderada. A interface avisa o usuário de que a IA externa não está configurada.
"""

from __future__ import annotations

import re
import time
from collections import Counter

from app.adapters.ai.base import AISuggestionRequest, AISuggestionResult, RawSuggestion
from app.modules.fields.types import role_before, to_snake_case

ROLES = (
    "CONTRATANTE",
    "CONTRATADA",
    "CONTRATADO",
    "LOCADOR",
    "LOCADORA",
    "LOCATÁRIO",
    "LOCATÁRIA",
    "OUTORGANTE",
    "OUTORGADO",
    "OUTORGADA",
    "COMPRADOR",
    "COMPRADORA",
    "VENDEDOR",
    "VENDEDORA",
    "EMPREGADOR",
    "EMPREGADO",
    "EMPREGADA",
    "DECLARANTE",
    "CEDENTE",
    "CESSIONÁRIO",
    "FIADOR",
    "LOCADORES",
    "PROMITENTE",
)
_ROLE_RE = re.compile(r"\b(" + "|".join(ROLES) + r")\s*:\s*([^,;\n]{3,80})")
_UP = "A-ZÀ-ÝÇ"
_LOW = "a-zà-ÿç"
_NAME_RE = re.compile(
    rf"\b[{_UP}][{_LOW}]+(?:\s+(?:d[aeo]s?|e)\s+[{_UP}][{_LOW}]+|\s+[{_UP}][{_LOW}]+){{1,4}}\b"
)
_COMPANY_RE = re.compile(
    rf"\b[{_UP}][\w&.\-]*(?:\s+[{_UP}\w&.\-]+){{0,6}}\s+(?:Ltda\.?|LTDA\.?|S\.?A\.?|EIRELI|EPP|ME)\b"
)
_POSITION_RE = re.compile(rf"\b(?:cargo|função)\s+de\s+([{_UP}{_LOW}][^,.;\n]{{2,60}})")
_TERM_RE = re.compile(r"\b(?:prazo|vigência|duração)\s+de\s+(\d{1,3}\s+(?:dias|meses|anos|semanas))", re.I)
_SERVICE_RE = re.compile(r"\bprestação\s+de\s+serviços\s+de\s+([^,.;\n]{5,90})", re.I)
_ADDRESS_RE = re.compile(
    r"\b(?:Rua|Av\.?|Avenida|Alameda|Travessa|Praça|Rodovia)\s+[^,\n]{3,60},\s*(?:n[ºo°]\s*)?\d+[^,.\n]{0,30}"
)
_YESNO_RE = re.compile(r"[:\-–]\s*(Sim|Não)\b")

STOP_PHRASES = {
    "São Paulo",
    "Rio De Janeiro",
    "Rio de Janeiro",
    "Código Civil",
    "Poder Judiciário",
    "Belo Horizonte",
    "Porto Alegre",
    "Distrito Federal",
    "Código Penal",
    "Estado De São Paulo",
}
STOP_FIRST_WORDS = {
    "Pela",
    "Pelo",
    "Para",
    "Como",
    "Este",
    "Esta",
    "Cláusula",
    "Contrato",
    "Parágrafo",
    "Artigo",
    "Documento",
    "Data",
    "Assinatura",
    "Foro",
    "Página",
    "Item",
    "Detalhe",
    "Valor",
    "Renovação",
    "Estúdio",
    "Pelas",
    "Pelos",
    "Todas",
    "Todos",
    "Nos",
    "Nas",
    "Das",
    "Dos",
    "Caso",
    "Após",
}


class LocalHeuristicProvider:
    name = "local"
    model = "heuristicas-locais-v1"

    def suggest(self, request: AISuggestionRequest) -> AISuggestionResult:
        started = time.monotonic()
        found: list[RawSuggestion] = []
        name_counts: Counter[str] = Counter()
        used = 0
        for b in request.blocks:
            used += len(b.text)
            if used > request.max_chars:
                break
            for m in _NAME_RE.finditer(b.text):
                cand = m.group(0)
                if cand in STOP_PHRASES or cand.split()[0] in STOP_FIRST_WORDS or len(cand) < 6:
                    continue
                name_counts[cand] += 1

        role_names: dict[
            str, tuple[str, str]
        ] = {}  # valor → (nome técnico, rótulo), para agrupar todas as ocorrências
        for b in request.blocks:
            for m in _ROLE_RE.finditer(b.text):
                role, value = m.group(1), m.group(2).strip()
                if "," in value or len(value) < 3:
                    continue
                role_names.setdefault(value, (f"nome_{to_snake_case(role)}", f"Nome — {role.capitalize()}"))

        # papel encontrado ANTES de cada nome que se repete (ex.: "...CONTRATANTE, Sr. João da Silva...") —
        # olhado na PRIMEIRA ocorrência do nome no documento e aplicado a todas as outras, pra um nome
        # repetido continuar virando um único campo (não um por ocorrência, mesmo com contextos diferentes).
        name_role: dict[str, str | None] = {}
        for cand, n in name_counts.items():
            if n < 2 or cand in role_names:
                continue
            role: str | None = None
            for b in request.blocks:
                for m in re.finditer(re.escape(cand), b.text):
                    role = role_before(b.text, m.start())
                    if role:
                        break
                if role:
                    break
            name_role[cand] = role

        for b in request.blocks:
            text = b.text
            for value, (rname, rlabel) in role_names.items():
                for _ in re.finditer(re.escape(value), text):
                    found.append(
                        self._make(
                            b.key,
                            value,
                            rname,
                            rlabel,
                            "text_short",
                            0.78,
                            "Aparece depois de um rótulo de parte (ex.: CONTRATANTE:)",
                        )
                    )
            for m in _COMPANY_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(0).strip(),
                        "razao_social",
                        "Razão social",
                        "text_short",
                        0.7,
                        "Termina com forma societária (Ltda., S.A. etc.)",
                    )
                )
            for m in _POSITION_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(1).strip(),
                        "cargo",
                        "Cargo",
                        "text_short",
                        0.62,
                        "Após 'cargo de/função de'",
                    )
                )
            for m in _TERM_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(1),
                        "prazo",
                        "Prazo",
                        "text_short",
                        0.6,
                        "Prazo/vigência informados no texto",
                    )
                )
            for m in _SERVICE_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(1).strip(),
                        "tipo_servico",
                        "Tipo de serviço",
                        "select",
                        0.58,
                        "Objeto da prestação de serviços (pode virar lista suspensa)",
                    )
                )
            for m in _ADDRESS_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(0).strip(),
                        "endereco",
                        "Endereço",
                        "text_short",
                        0.6,
                        "Parece um endereço",
                    )
                )
            for m in _YESNO_RE.finditer(text):
                found.append(
                    self._make(
                        b.key,
                        m.group(1),
                        "opcao_sim_nao",
                        "Opção (Sim/Não)",
                        "yes_no",
                        0.45,
                        "Resposta Sim/Não após dois-pontos",
                    )
                )
            for cand, n in name_counts.items():
                if n < 2 or cand in role_names:
                    continue
                role = name_role.get(cand)
                rname = to_snake_case(role) if role else "nome_pessoa"
                rlabel = role.capitalize() if role else "Nome"
                reason = (
                    f"Nome próprio que se repete no documento ({n}x), após um rótulo de parte ({role})"
                    if role
                    else f"Nome próprio que se repete no documento ({n}x)"
                )
                for m in re.finditer(re.escape(cand), text):
                    found.append(
                        self._make(
                            b.key,
                            cand,
                            rname,
                            rlabel,
                            "text_short",
                            0.66,
                            reason,
                            start_hint=m.start(),
                        )
                    )
        return AISuggestionResult(
            suggestions=found,
            provider=self.name,
            model=self.model,
            chars_sent=0,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _make(
        block: str,
        text: str,
        name: str,
        label: str,
        typ: str,
        conf: float,
        reason: str,
        start_hint: int | None = None,
    ) -> RawSuggestion:
        return RawSuggestion(
            block=block,
            text=text[:300],
            name=name[:64],
            label=label[:200],
            type=typ,
            confidence=conf,
            reason=reason,
        )

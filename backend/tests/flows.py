"""Fluxos reutilizáveis nos testes de API: monta um gerador completo simulando o que o editor faz."""

from __future__ import annotations

import io
from typing import Any

from docx import Document

from app.docx_engine.inline import inline_text
from app.docx_engine.nodes import replace_range_with_field
from tests.conftest import Api


def iter_paragraphs(doc: dict[str, Any]):
    def walk(nodes):
        for n in nodes:
            if n["type"] == "paragraph":
                yield n
            for key in ("content",):
                if n["type"] in ("docPart", "table", "tableRow", "tableCell") and key in n:
                    yield from walk(n[key])

    yield from walk(doc["content"])


def apply_field(doc: dict[str, Any], block_key: str, needle: str, field_id: str) -> None:
    """Equivale a: selecionar `needle` no bloco e 'Transformar em campo' (edita o JSON do documento)."""
    for p in iter_paragraphs(doc):
        if p["attrs"]["blockKey"] == block_key:
            text = inline_text(p.get("content", []))
            start = text.index(needle)
            p["content"], _ = replace_range_with_field(p["content"], start, start + len(needle), field_id)
            return
    raise AssertionError(f"bloco {block_key} não encontrado")


def create_field(api: Api, gid: str, **data: Any) -> dict[str, Any]:
    r = api.post(f"/generators/{gid}/fields", json=data)
    assert r.status_code == 201, r.text
    return r.json()


def upload(api: Api, gid: str, content: bytes, filename: str = "contrato.docx"):  # type: ignore[no-untyped-def]
    return api.post(
        f"/generators/{gid}/template", files={"file": (filename, content, "application/octet-stream")}
    )


SERVICES = [
    {"label": "Consultoria em desenvolvimento de software"},
    {"label": "Suporte técnico mensal"},
    {"label": "Treinamento de equipes"},
]


def build_generator(
    api: Api, demo_docx: bytes, *, name: str = "Contrato de prestação de serviços"
) -> dict[str, Any]:
    """Cria gerador, envia o DOCX e cria 7 campos ancorados no texto. Já fica pronto para gerar (sem publicação)."""
    g = api.post("/generators", json={"name": name, "description": "Contrato padrão de serviços"})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    up = upload(api, gid, demo_docx)
    assert up.status_code == 201, up.text

    ed = api.get(f"/generators/{gid}/editor").json()
    doc, revision = ed["doc"], ed["version"]["revision"]

    nome = create_field(api, gid, label="Nome do contratante", type="text_short", required=True)
    cpf = create_field(api, gid, label="CPF do contratante", type="cpf", required=True)
    cnpj = create_field(api, gid, label="CNPJ da contratada", type="cnpj")
    servico = create_field(api, gid, label="Tipo de serviço", type="select", required=True, options=SERVICES)
    valor = create_field(api, gid, label="Valor mensal", type="currency", required=True)
    inicio = create_field(api, gid, label="Data de início", type="date", required=True)
    renov = create_field(api, gid, label="Renovação automática", type="yes_no")
    fields = {
        "nome": nome,
        "cpf": cpf,
        "cnpj": cnpj,
        "servico": servico,
        "valor": valor,
        "inicio": inicio,
        "renov": renov,
    }

    # o "João da Silva" aparece em 4 lugares (corpo, tabela, assinatura, rodapé)
    for key in ("body/p3", "body/p5", "body/t1/r2/c2/p1", "body/p11", "footer1/p1"):
        apply_field(doc, key, "João da Silva", nome["id"])
    apply_field(doc, "body/p3", "123.456.789-09", cpf["id"])
    apply_field(doc, "body/p4", "11.222.333/0001-81", cnpj["id"])
    apply_field(doc, "body/p5", "consultoria em desenvolvimento de software", servico["id"])
    apply_field(doc, "body/p6", "R$ 5.000,00", valor["id"])
    apply_field(doc, "body/t1/r3/c2/p1", "R$ 5.000,00", valor["id"])
    apply_field(doc, "body/p7", "01/10/2026", inicio["id"])
    apply_field(doc, "body/p7", "Sim", renov["id"])

    saved = api.put(f"/generators/{gid}/editor/content", json={"revision": revision, "doc": doc})
    assert saved.status_code == 200, saved.text
    return {
        "id": gid,
        "fields": fields,
        "revision": saved.json()["revision"],
        "occurrences": saved.json()["occurrences"],
    }


SAMPLE_VALUES = {
    "nome_do_contratante": "Maria Souza",
    "cpf_do_contratante": "529.982.247-25",
    "cnpj_da_contratada": "11.222.333/0001-81",
    "tipo_de_servico": "Suporte técnico mensal",
    "valor_mensal": "1.234,50",
    "data_de_inicio": "15/11/2026",
    "renovacao_automatica": "Não",
}


def docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    parts += [c.text for t in doc.tables for row in t.rows for c in row.cells]
    parts += [p.text for s in doc.sections for p in list(s.header.paragraphs) + list(s.footer.paragraphs)]
    return "\n".join(parts)

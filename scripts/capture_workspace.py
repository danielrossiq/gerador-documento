"""Cria, na stack de teste, uma conta descartável com o contrato de exemplo SEM imagem e SEM quebra de página, para as
capturas da landing (landing-spec-v2 §9: sem o aviso de elementos avançados). Dados fictícios; a conta de
demonstração do seed não muda. Roda DENTRO do contêiner da API da minuta-fase0:

    docker exec -i minuta-fase0-api-1 python - < scripts/capture_workspace.py

Imprime o e-mail da conta (senha: senha-forte-123). Nunca rode na stack `minuta`.
"""

from __future__ import annotations

import io
import time

from app.db.session import get_factory
from app.modules.auth import service as auth
from app.modules.samples import documents
from app.modules.samples import service as samples
from docx import Document
from docx.oxml.ns import qn
from seed.seed import _ctx

PASSWORD = "senha-forte-123"


def clean_contract() -> bytes:
    """Mesmo contrato do exemplo, sem o logo e sem a quebra de página. Os parágrafos ficam (vazios), então as chaves
    de bloco usadas pelo exemplo (body/p3, body/p5…) não mudam."""
    doc = Document(io.BytesIO(documents.build_demo_contract()))
    body = doc.element.body
    for el in list(body.iter(qn("w:drawing"))):
        el.getparent().remove(el)
    for br in list(body.iter(qn("w:br"))):
        if br.get(qn("w:type")) == "page":
            br.getparent().remove(br)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def main() -> None:
    samples.build_demo_contract = clean_contract
    email = f"capturas-{int(time.time())}@exemplo.test"
    with get_factory()() as db:
        user, ws = auth.register(
            db,
            name="Ana Souza",
            email=email,
            password=PASSWORD,
            workspace_name="Escritório Exemplo",
            ip="capturas",
        )
        db.commit()
        samples.create_sample_contract(_ctx(db, user, ws), "Contrato de prestação de serviços", None)
    print(email)


main()

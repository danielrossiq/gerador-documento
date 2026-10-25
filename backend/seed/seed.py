"""Dados de demonstração (fictícios). Usa os mesmos serviços da API — não grava direto no banco.

Cria: workspace + usuário de demonstração, o gerador "Contrato de prestação de serviços" (DOCX de exemplo,
6 campos + renovação, lista de serviços), um lote de exemplo (planilhas em demo/) e um segundo workspace vazio
para demonstrar o isolamento entre tenants.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.models import User, UserSession, Workspace, WorkspaceMember
from app.db.session import get_factory
from app.modules.auth import service as auth
from app.modules.generation import service as generation
from app.modules.generators import service as generators
from app.modules.samples import service as samples

DEMO_EMAIL = "demo@docfeito.com.br"
OTHER_EMAIL = "outra@docfeito.com.br"
DEMO_LIMITS = {"max_docs_per_month": 20000, "max_generators": 200, "max_batch_rows": 1000, "max_ai_actions_per_month": 200}

SAMPLE_ROWS = [
    {
        "nome_do_contratante": "Ana Beatriz Lima",
        "cpf_do_contratante": "529.982.247-25",
        "tipo_de_servico": "Consultoria em desenvolvimento de software",
        "valor_mensal": "5.000,00",
        "data_de_inicio": "01/10/2026",
        "renovacao_automatica": "Sim",
    },
    {
        "nome_do_contratante": "Carlos Eduardo Rocha",
        "cpf_do_contratante": "111.444.777-35",
        "tipo_de_servico": "Suporte técnico mensal",
        "valor_mensal": "1.850,50",
        "data_de_inicio": "15/10/2026",
        "renovacao_automatica": "Não",
    },
    {
        "nome_do_contratante": "Fernanda Souza",
        "cpf_do_contratante": "390.533.447-05",
        "tipo_de_servico": "Treinamento de equipes",
        "valor_mensal": "3.200,00",
        "data_de_inicio": "03/11/2026",
        "renovacao_automatica": "Sim",
    },
    # linha inválida de propósito (CPF com dígito verificador errado e valor não numérico) para demonstrar a correção na grade
    {
        "nome_do_contratante": "Diego Martins",
        "cpf_do_contratante": "123.456.789-00",
        "tipo_de_servico": "Auditoria de processos",
        "valor_mensal": "mil reais",
        "data_de_inicio": "20/11/2026",
        "renovacao_automatica": "Não",
    },
]


def _ctx(db, user: User, ws: Workspace) -> Ctx:
    session = db.scalar(select(UserSession).where(UserSession.user_id == user.id)) or UserSession(
        user_id=user.id, workspace_id=ws.id, token_hash="seed", csrf_token="seed", expires_at=utcnow()
    )
    return Ctx(db, user, ws, "owner", session, None, None)


def _ensure_user(db, email: str, name: str, workspace_name: str, password: str) -> tuple[User, Workspace]:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
        return user, db.get(Workspace, member.workspace_id)  # type: ignore[union-attr,arg-type]
    user, ws = auth.register(
        db, name=name, email=email, password=password, workspace_name=workspace_name, ip="seed"
    )
    user.password_hash = hash_password(password)
    db.commit()
    return user, ws


def run_seed() -> int:
    password = get_settings().seed_demo_password
    with get_factory()() as db:
        user, ws = _ensure_user(
            db, DEMO_EMAIL, "Usuária Demonstração", "Empresa Demonstração Ltda.", password
        )
        _ensure_user(db, OTHER_EMAIL, "Outra Empresa", "Outra Empresa (isolamento)", password)
        # conta de demonstração com limites próprios: com a cobrança ligada ela não cai nos limites do plano Grátis
        if not ws.limits:
            ws.limits = dict(DEMO_LIMITS)
            db.commit()
        ctx = _ctx(db, user, ws)

        existing = list(
            generators.list_generators(
                ctx, q="Contrato de prestação", status=None, page=1, page_size=5, sort="name"
            )["items"]
        )
        complete = [g for g in existing if g["documents_generated"] > 0]
        if complete:
            print(f"seed: já existe (login: {DEMO_EMAIL})")
            return 0
        for partial in existing:  # execução anterior interrompida: descarta o resíduo e refaz do zero
            generators.delete_generator(ctx, uuid.UUID(partial["id"]))

        gen = samples.create_sample_contract(
            ctx, "Contrato de prestação de serviços", "Modelo padrão para contratação de serviços recorrentes"
        )

        # histórico de exemplo: 1 geração individual + 1 lote com uma linha inválida (concluído parcialmente)
        generation.create_single(
            ctx, gen.id, generation.SingleIn(values=SAMPLE_ROWS[0], format="docx"), "seed-single-1"
        )
        generation.create_batch(
            ctx, gen.id, generation.BatchIn(rows=SAMPLE_ROWS, format="docx", only_valid=True), "seed-batch-1"
        )
    print(f"seed concluído. Login: {DEMO_EMAIL} / {password}  (outro workspace: {OTHER_EMAIL})")
    return 0

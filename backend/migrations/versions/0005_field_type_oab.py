"""tipo de campo OAB (inscrição de advogado) em fields e kit_fields

Revision ID: 0005
Revises: 0004

O tipo é validado por CHECK nas duas tabelas; esta migration só troca a lista de tipos permitidos.
Downgrade: campos "oab" viram "text_short" (o valor guardado — ex.: "ES 12345" — continua legível como texto)
antes de recriar a restrição antiga, para o downgrade não falhar com dados existentes.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OLD = (
    "text_short", "text_long", "number", "currency", "date", "cpf", "cnpj", "cep",
    "email", "phone", "select", "yes_no", "checkbox",
)  # fmt: skip
NEW = (
    "text_short", "text_long", "number", "currency", "date", "cpf", "cnpj", "cep",
    "email", "phone", "oab", "select", "yes_no", "checkbox",
)  # fmt: skip
TABLES = ("fields", "kit_fields")


def _in(values: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _swap(values: tuple[str, ...]) -> None:
    for table in TABLES:
        name = op.f(f"ck_{table}_type")
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _in(values))


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    op.execute("UPDATE fields SET type = 'text_short' WHERE type = 'oab'")
    op.execute("UPDATE kit_fields SET type = 'text_short' WHERE type = 'oab'")
    _swap(OLD)

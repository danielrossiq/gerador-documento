"""Modelos e kit de exemplo, prontos para preencher — "experimentar sem ter um .docx à mão" (D27).

Usa os mesmos serviços da API (criar gerador, enviar .docx, criar campos, aplicar no texto), então o resultado é
um modelo comum do workspace: pode ser editado, usado, gerado em lote ou excluído como qualquer outro.
"""

from __future__ import annotations

from app.core.deps import Ctx
from app.db.models import DocumentGenerator, DocumentKit
from app.modules.fields import service as fields
from app.modules.generators import service as generators
from app.modules.kits import service as kits
from app.modules.samples.documents import DEMO_SERVICES, build_demo_contract, build_demo_receipt
from app.modules.templates import core
from app.modules.templates import service as templates

CONTRACT_NAME = "Contrato de prestação de serviços (exemplo)"
RECEIPT_NAME = "Recibo de pagamento (exemplo)"
KIT_NAME = "Kit contratação (exemplo)"


def create_sample_contract(
    ctx: Ctx, name: str = CONTRACT_NAME, description: str | None = "Exemplo pronto para preencher"
) -> DocumentGenerator:
    gen = generators.create_generator(ctx, name, description)
    version = templates.upload_template(
        ctx, gen.id, "contrato_prestacao_servicos.docx", build_demo_contract()
    )
    version = core.get_version(ctx.db, ctx.workspace_id, version.id)

    def field(label: str, ftype: str, **kw):  # type: ignore[no-untyped-def]
        return fields.create_field(ctx, gen.id, fields.FieldIn(label=label, type=ftype, **kw))

    nome = field(
        "Nome do contratante", "text_short", required=True, description="Nome completo de quem contrata"
    )
    cpf = field("CPF do contratante", "cpf", required=True)
    cnpj = field("CNPJ da contratada", "cnpj", include_in_batch=False, default_value="11.222.333/0001-81")
    servico = field(
        "Tipo de serviço",
        "select",
        required=True,
        options=[fields.OptionIn(label=lb, value=v) for lb, v in DEMO_SERVICES],
    )
    valor = field("Valor mensal", "currency", required=True, description="Valor cobrado por mês")
    inicio = field("Data de início", "date", required=True)
    renov = field("Renovação automática", "yes_no", default_value="Sim")

    def apply(key: str, text: str, f) -> None:  # type: ignore[no-untyped-def]
        templates.apply_field_to_block(ctx, version, key, text, f.id)

    for key in ("body/p3", "body/p5", "body/t1/r2/c2/p1", "body/p11", "footer1/p1"):
        apply(key, "João da Silva", nome)
    apply("body/p3", "123.456.789-09", cpf)
    apply("body/p4", "11.222.333/0001-81", cnpj)
    apply("body/p5", "consultoria em desenvolvimento de software", servico)
    apply("body/p6", "R$ 5.000,00", valor)
    apply("body/t1/r3/c2/p1", "R$ 5.000,00", valor)
    apply("body/p7", "01/10/2026", inicio)
    apply("body/p7", "Sim", renov)
    core.recompute_occurrences(ctx.db, version)
    core.touch(version, gen, content=True)
    generators.update_generator(ctx, gen.id, {"filename_pattern": "Contrato_{nome_do_contratante}_{hoje}"})
    ctx.db.commit()
    return gen


def create_sample_receipt(ctx: Ctx) -> DocumentGenerator:
    """Mesmos rótulos do contrato para nome, CPF e valor — é o que faz o kit de exemplo juntá-los sozinho."""
    gen = generators.create_generator(ctx, RECEIPT_NAME, "Exemplo pronto para preencher")
    version = templates.upload_template(ctx, gen.id, "recibo_pagamento.docx", build_demo_receipt())
    version = core.get_version(ctx.db, ctx.workspace_id, version.id)

    def field(label: str, ftype: str, **kw):  # type: ignore[no-untyped-def]
        return fields.create_field(ctx, gen.id, fields.FieldIn(label=label, type=ftype, **kw))

    nome = field("Nome do contratante", "text_short", required=True)
    cpf = field("CPF do contratante", "cpf", required=True)
    valor = field("Valor mensal", "currency", required=True)
    mes = field("Mês de referência", "text_short", required=True, example="outubro de 2026")
    pago = field("Data do pagamento", "date", required=True)

    def apply(key: str, text: str, f) -> None:  # type: ignore[no-untyped-def]
        templates.apply_field_to_block(ctx, version, key, text, f.id)

    apply("body/p2", "João da Silva", nome)
    apply("body/p2", "123.456.789-09", cpf)
    apply("body/p2", "R$ 5.000,00", valor)
    apply("body/p2", "outubro de 2026", mes)
    apply("body/p3", "05/10/2026", pago)
    core.recompute_occurrences(ctx.db, version)
    core.touch(version, gen, content=True)
    generators.update_generator(ctx, gen.id, {"filename_pattern": "Recibo_{nome_do_contratante}_{hoje}"})
    ctx.db.commit()
    return gen


def create_sample_kit(ctx: Ctx) -> DocumentKit:
    """Contrato + recibo de exemplo num kit, com os campos em comum (nome, CPF, valor) já detectados."""
    contract = create_sample_contract(ctx)
    receipt = create_sample_receipt(ctx)
    kit = kits.create_kit(ctx, KIT_NAME, "Contrato e recibo preenchidos de uma vez")
    kits.add_item(ctx, kit.id, contract.id)
    kits.add_item(ctx, kit.id, receipt.id)
    kits.auto_detect(ctx, kit.id)
    return kits.get_kit(ctx.db, ctx.workspace_id, kit.id)

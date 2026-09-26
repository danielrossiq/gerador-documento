"""Modelo e kit de exemplo ("experimentar sem ter um .docx à mão") e o contexto de kit no histórico."""

from __future__ import annotations

import uuid


def test_sample_generator_is_ready_to_fill(api):
    api.register()
    r = api.post("/samples/generator")
    assert r.status_code == 201, r.text
    gen = r.json()
    assert gen["has_template"] and gen["fields_count"] == 7

    form = api.get(f"/generators/{gen['id']}/form").json()
    names = {f["name"] for f in form["fields"]}
    assert {"nome_do_contratante", "cpf_do_contratante", "tipo_de_servico", "valor_mensal"} <= names

    # já dá pra gerar direto, sem passar pelo editor
    job = api.post(
        f"/generators/{gen['id']}/generate",
        json={
            "values": {
                "nome_do_contratante": "Maria Souza",
                "cpf_do_contratante": "529.982.247-25",
                "tipo_de_servico": "Suporte técnico mensal",
                "valor_mensal": "1.234,50",
                "data_de_inicio": "15/11/2026",
            },
            "format": "docx",
        },
    )
    assert job.status_code == 202, job.text


def test_sample_kit_links_contract_and_receipt_by_shared_fields(api):
    api.register()
    r = api.post("/samples/kit")
    assert r.status_code == 201, r.text
    kit = r.json()
    assert kit["items_count"] == 2 and kit["has_documents"]

    form = api.get(f"/kits/{kit['id']}/form").json()
    shared = {f["label"] for f in form["fields"]}
    assert {"Nome do contratante", "CPF do contratante", "Valor mensal"} <= shared
    extras = {m["generator_name"]: set(m["extra_field_names"]) for m in form["members"]}
    receipt = next(v for k, v in extras.items() if k.startswith("Recibo"))
    assert {
        "mes_de_referencia",
        "data_do_pagamento",
    } <= receipt  # campos só do recibo continuam por documento


def test_history_identifies_kit_documents_and_filters_them(api):
    api.register()
    kit = api.post("/samples/kit").json()
    form = api.get(f"/kits/{kit['id']}/form").json()
    by_label = {f["label"]: f["name"] for f in form["fields"]}
    member_values = {}
    for m in form["members"]:
        vals = {}
        for name in m["extra_field_names"]:
            if name == "tipo_de_servico":
                vals[name] = "Suporte técnico mensal"
            elif name in ("data_de_inicio", "data_do_pagamento"):
                vals[name] = "15/11/2026"
            elif name == "mes_de_referencia":
                vals[name] = "novembro de 2026"
        member_values[m["generator_id"]] = vals
    run = api.post(
        f"/kits/{kit['id']}/runs",
        json={
            "values": {
                by_label["Nome do contratante"]: "Maria Souza",
                by_label["CPF do contratante"]: "529.982.247-25",
                by_label["Valor mensal"]: "1.234,50",
            },
            "member_values": member_values,
            "format": "docx",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert run.status_code == 202, run.text

    kit_jobs = api.get("/jobs?kind=kit").json()
    assert kit_jobs["total"] == 2
    assert all(j["kit_name"] == "Kit contratação (exemplo)" for j in kit_jobs["items"])
    # "individuais" não mistura os documentos que vieram de um kit
    assert api.get("/jobs?kind=single").json()["total"] == 0

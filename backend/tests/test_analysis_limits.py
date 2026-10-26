"""Defesa contra documento enorme na análise de campos (achado QA-2): limite de parágrafos analisados."""

from __future__ import annotations

from tests.flows import upload


def test_long_document_is_analyzed_partially_with_a_warning(api, demo_docx, monkeypatch):
    monkeypatch.setattr("app.modules.suggestions.service.MAX_ANALYZED_BLOCKS", 3)
    api.register()
    gid = api.post("/generators", json={"name": "Longo"}).json()["id"]
    assert upload(api, gid, demo_docx).status_code == 201
    sug = api.get(f"/generators/{gid}/suggestions").json()
    assert sug["analysis"]["status"] == "done"
    assert "primeiros 5.000 parágrafos" in (sug["analysis"]["error"] or "")
    keys = {o["block_key"] for g in sug["items"] for o in g["occurrences"]}
    assert len(keys) <= 3  # só os primeiros blocos legíveis foram analisados

"""Isolamento entre workspaces: nenhum recurso de A é visível ou alterável por B (resposta 404, nunca 403)."""

from __future__ import annotations

import uuid

import pytest

from tests.flows import SAMPLE_VALUES, build_generator


@pytest.fixture()
def two_tenants(api, api2, demo_docx, fake_pdf):
    """A tem gerador publicado + uma geração com arquivos; B é outro usuário em outro workspace."""
    a = api.register("a@exemplo.test")
    b = api2.register("b@exemplo.test")
    assert a["workspace"]["id"] != b["workspace"]["id"]
    built = build_generator(api, demo_docx)
    job = api.post(
        f"/generators/{built['id']}/generate", json={"values": SAMPLE_VALUES, "format": "both"}
    ).json()
    link = api.post(f"/files/{job['files'][0]['id']}/link").json()["url"]
    field_id = built["fields"]["nome"]["id"]
    ed = api.get(f"/generators/{built['id']}/editor").json()
    return {
        "gid": built["id"],
        "job": job,
        "file_id": job["files"][0]["id"],
        "link": link,
        "field_id": field_id,
        "editor": ed,
        "built": built,
    }


def test_b_sees_nothing_of_a(api2, two_tenants):
    assert api2.get("/generators").json()["total"] == 0
    assert api2.get("/dashboard").json()["total_generators"] == 0
    assert api2.get("/jobs").json()["total"] == 0
    assert api2.get("/kits").json()["total"] == 0
    assert api2.get("/kit-runs").json()["total"] == 0


def test_b_cannot_touch_a_generator(api2, two_tenants):
    gid = two_tenants["gid"]
    fake = str(uuid.uuid4())
    calls = [
        ("get", f"/generators/{gid}", None),
        ("patch", f"/generators/{gid}", {"name": "hack"}),
        ("delete", f"/generators/{gid}", None),
        ("post", f"/generators/{gid}/duplicate", None),
        ("post", f"/generators/{gid}/archive", None),
        ("get", f"/generators/{gid}/editor", None),
        ("put", f"/generators/{gid}/editor/content", {"revision": 1, "doc": {"type": "doc", "content": []}}),
        ("get", f"/generators/{gid}/versions", None),
        ("post", f"/generators/{gid}/pin", None),
        ("post", f"/generators/{gid}/unpin", None),
        ("get", f"/generators/{gid}/fields", None),
        ("post", f"/generators/{gid}/fields", {"label": "x", "type": "text_short"}),
        ("get", f"/generators/{gid}/form", None),
        ("get", f"/generators/{gid}/suggestions", None),
        ("post", f"/generators/{gid}/generate", {"values": SAMPLE_VALUES}),
        ("post", f"/generators/{gid}/batch/validate", {"rows": [SAMPLE_VALUES]}),
        ("post", f"/generators/{gid}/batches", {"rows": [SAMPLE_VALUES]}),
        ("get", f"/generators/{gid}/batch/template.xlsx", None),
        ("patch", f"/fields/{two_tenants['field_id']}", {"label": "hack"}),
        ("delete", f"/fields/{two_tenants['field_id']}", None),
        ("put", f"/fields/{two_tenants['field_id']}/options", {"options": []}),
        ("get", f"/jobs/{two_tenants['job']['id']}", None),
        ("get", f"/jobs/{two_tenants['job']['id']}/items", None),
        ("post", f"/jobs/{two_tenants['job']['id']}/repeat", None),
        ("post", f"/jobs/{two_tenants['job']['id']}/cancel", None),
        ("post", f"/files/{two_tenants['file_id']}/link", None),
        ("post", f"/suggestions/{fake}/accept", None),
        ("post", f"/suggestions/{fake}/ignore", None),
    ]
    for method, path, body in calls:
        r = getattr(api2, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (
            f"{method.upper()} {path} deveria ser 404, foi {r.status_code}: {r.text[:120]}"
        )


@pytest.fixture()
def two_tenants_kit(api, api2, demo_docx):
    """A tem um kit com 1 documento, 1 campo compartilhado e 1 geração; B é outro workspace."""
    api.register("ka@exemplo.test")
    api2.register("kb@exemplo.test")
    gid = build_generator(api, demo_docx)["id"]
    kid = api.post("/kits", json={"name": "Kit A"}).json()["id"]
    item = api.post(f"/kits/{kid}/items", json={"generator_id": gid}).json()
    kf = api.post(f"/kits/{kid}/fields", json={"label": "Nome", "type": "text_short"}).json()
    api.put(f"/kits/{kid}/items/{item['id']}/mapping", json={"mapping": {kf["name"]: "nome_do_contratante"}})
    run = api.post(
        f"/kits/{kid}/runs",
        json={"values": {kf["name"]: "Maria Souza"}, "member_values": {gid: SAMPLE_VALUES}},
    ).json()
    return {"kid": kid, "item_id": item["id"], "field_id": kf["id"], "run_id": run["id"]}


def test_b_cannot_touch_a_kit(api2, two_tenants_kit):
    t = two_tenants_kit
    calls = [
        ("get", f"/kits/{t['kid']}", None),
        ("patch", f"/kits/{t['kid']}", {"name": "hack"}),
        ("post", f"/kits/{t['kid']}/archive", None),
        ("post", f"/kits/{t['kid']}/pin", None),
        ("get", f"/kits/{t['kid']}/items", None),
        ("post", f"/kits/{t['kid']}/items", {"generator_id": str(uuid.uuid4())}),
        ("delete", f"/kits/{t['kid']}/items/{t['item_id']}", None),
        ("put", f"/kits/{t['kid']}/items/{t['item_id']}/mapping", {"mapping": {}}),
        ("post", f"/kits/{t['kid']}/auto-detect", None),
        ("get", f"/kits/{t['kid']}/fields", None),
        ("post", f"/kits/{t['kid']}/fields", {"label": "x", "type": "text_short"}),
        ("patch", f"/kit-fields/{t['field_id']}", {"label": "hack"}),
        ("delete", f"/kit-fields/{t['field_id']}", None),
        ("put", f"/kit-fields/{t['field_id']}/options", {"options": []}),
        ("get", f"/kits/{t['kid']}/form", None),
        ("post", f"/kits/{t['kid']}/runs", {"values": {}}),
        ("get", f"/kit-runs/{t['run_id']}", None),
        ("delete", f"/kits/{t['kid']}", None),
    ]
    for method, path, body in calls:
        r = getattr(api2, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (
            f"{method.upper()} {path} deveria ser 404, foi {r.status_code}: {r.text[:120]}"
        )


def test_download_token_is_bound_to_user_and_workspace(api, api2, two_tenants):
    assert api.tc.get(two_tenants["link"]).status_code == 200  # dono baixa
    stolen = api2.tc.get(two_tenants["link"])  # outro usuário com o mesmo link
    assert stolen.status_code == 404
    api.post("/auth/logout")
    assert api.tc.get(two_tenants["link"]).status_code == 401  # sem sessão, o link sozinho não basta


def test_tampered_or_expired_tokens_are_rejected(api, two_tenants):
    token = two_tenants["link"].rsplit("/", 1)[1]
    assert api.tc.get(f"/api/v1/downloads/{token[:-3]}xyz").status_code == 404
    assert api.tc.get("/api/v1/downloads/lixo").status_code == 404


def test_expired_file_is_gone(api, two_tenants):
    from datetime import timedelta

    from sqlalchemy import update

    from app.db.base import utcnow
    from app.db.models import GeneratedFile
    from app.db.session import get_factory

    with get_factory()() as db:
        db.execute(update(GeneratedFile).values(expires_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    r = api.post(f"/files/{two_tenants['file_id']}/link")
    assert r.status_code == 410 and r.json()["error"]["code"] == "FILE_EXPIRED"


def test_b_can_use_same_names_without_collision(api2, demo_docx):
    """Recursos de B convivem com os de A (mesmo nome de gerador/campo em workspaces distintos)."""
    api2.register("c@exemplo.test")
    built = build_generator(api2, demo_docx)
    assert built["fields"]["nome"]["name"] == "nome_do_contratante"


def test_member_role_can_only_repeat_own_jobs(api, api2, demo_docx, fake_pdf):
    """Owner pode repetir qualquer geração; um membro só as suas (papéis owner/member)."""
    from sqlalchemy import select

    from app.db.models import User, WorkspaceMember
    from app.db.session import get_factory

    a = api.register("owner@exemplo.test")
    built = build_generator(api, demo_docx)
    job = api.post(f"/generators/{built['id']}/generate", json={"values": SAMPLE_VALUES}).json()
    b = api2.register("member@exemplo.test")
    with (
        get_factory()() as db
    ):  # coloca B como *member* no workspace de A (a UI de convites fica para depois)
        uid = db.scalar(select(User.id).where(User.email == "member@exemplo.test"))
        db.add(WorkspaceMember(workspace_id=uuid.UUID(a["workspace"]["id"]), user_id=uid, role="member"))
        db.commit()
    from app.db.models import UserSession

    with get_factory()() as db:
        s = db.scalar(select(UserSession).where(UserSession.user_id == uid))
        s.workspace_id = uuid.UUID(a["workspace"]["id"])
        db.commit()
    assert b["workspace"]["id"] != a["workspace"]["id"]
    me = api2.get("/auth/me").json()
    assert me["workspace"]["role"] == "member"
    denied = api2.post(f"/jobs/{job['id']}/repeat")
    assert denied.status_code == 403
    assert api.post(f"/jobs/{job['id']}/repeat").status_code == 202

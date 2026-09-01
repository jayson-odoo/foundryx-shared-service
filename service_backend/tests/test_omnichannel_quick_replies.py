"""Quick-reply (canned response) CRUD tests - plan sprint-3/12.

Covers create/list/update/delete happy paths, tenant + workspace scoping,
shortcut-collision 409, empty-body 422, and the `workspaces.manage` perm gate.
Reads stay gated `conversations.read`; writes gated `workspaces.manage`.
"""
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(session_factory) -> str:
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    wid = ws.id
    db.close()
    return wid


def _make_workspace(session_factory, name="Second") -> str:
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name=name,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False,
        is_trashed=False,
    )
    db.add(ws)
    db.commit()
    wid = ws.id
    db.close()
    return wid


def test_quick_reply_crud_happy_path(client, session_factory):
    ws = _default_workspace_id(session_factory)
    h = _auth(client)

    # Create
    res = client.post(
        f"/omnichannel/workspaces/{ws}/quick-replies",
        headers=h,
        json={"shortcut": "  /hi ", "body": "  Hello there!  "},
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["shortcut"] == "/hi"  # normalized (stripped)
    assert created["body"] == "Hello there!"  # stripped
    assert created["workspaceId"] == ws
    qr_id = created["id"]

    # List (read gate = conversations.read; admin holds it)
    res = client.get(f"/omnichannel/workspaces/{ws}/quick-replies", headers=h)
    assert res.status_code == 200
    assert any(q["id"] == qr_id for q in res.json())

    # Update body + shortcut
    res = client.patch(
        f"/omnichannel/workspaces/{ws}/quick-replies/{qr_id}",
        headers=h,
        json={"body": "Updated body", "shortcut": "/hello"},
    )
    assert res.status_code == 200
    assert res.json()["body"] == "Updated body"
    assert res.json()["shortcut"] == "/hello"

    # Clear shortcut (explicit null)
    res = client.patch(
        f"/omnichannel/workspaces/{ws}/quick-replies/{qr_id}",
        headers=h,
        json={"shortcut": None},
    )
    assert res.status_code == 200
    assert res.json()["shortcut"] is None
    assert res.json()["body"] == "Updated body"  # untouched

    # Delete
    res = client.delete(
        f"/omnichannel/workspaces/{ws}/quick-replies/{qr_id}", headers=h
    )
    assert res.status_code == 204
    res = client.get(f"/omnichannel/workspaces/{ws}/quick-replies", headers=h)
    assert not any(q["id"] == qr_id for q in res.json())


def test_quick_reply_empty_body_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    h = _auth(client)
    res = client.post(
        f"/omnichannel/workspaces/{ws}/quick-replies",
        headers=h,
        json={"body": "   "},
    )
    assert res.status_code == 422


def test_quick_reply_shortcut_collision_409(client, session_factory):
    ws = _default_workspace_id(session_factory)
    h = _auth(client)
    client.post(
        f"/omnichannel/workspaces/{ws}/quick-replies",
        headers=h,
        json={"shortcut": "/dup", "body": "First"},
    )
    # Second create with the same shortcut → 409.
    res = client.post(
        f"/omnichannel/workspaces/{ws}/quick-replies",
        headers=h,
        json={"shortcut": "/dup", "body": "Second"},
    )
    assert res.status_code == 409

    # Update another row onto the taken shortcut → 409.
    other = client.post(
        f"/omnichannel/workspaces/{ws}/quick-replies",
        headers=h,
        json={"shortcut": "/other", "body": "Other"},
    ).json()
    res = client.patch(
        f"/omnichannel/workspaces/{ws}/quick-replies/{other['id']}",
        headers=h,
        json={"shortcut": "/dup"},
    )
    assert res.status_code == 409


def test_quick_reply_same_shortcut_different_workspace_ok(client, session_factory):
    ws_a = _default_workspace_id(session_factory)
    ws_b = _make_workspace(session_factory)
    h = _auth(client)
    a = client.post(
        f"/omnichannel/workspaces/{ws_a}/quick-replies",
        headers=h,
        json={"shortcut": "/greet", "body": "A"},
    )
    assert a.status_code == 201
    # Same shortcut in a DIFFERENT workspace is allowed (scoped uniqueness).
    b = client.post(
        f"/omnichannel/workspaces/{ws_b}/quick-replies",
        headers=h,
        json={"shortcut": "/greet", "body": "B"},
    )
    assert b.status_code == 201


def test_quick_reply_workspace_scoping_404(client, session_factory):
    ws_a = _default_workspace_id(session_factory)
    ws_b = _make_workspace(session_factory)
    h = _auth(client)
    qr = client.post(
        f"/omnichannel/workspaces/{ws_a}/quick-replies",
        headers=h,
        json={"body": "In A"},
    ).json()
    # The row lives in workspace A - addressing it via workspace B is a 404.
    res = client.patch(
        f"/omnichannel/workspaces/{ws_b}/quick-replies/{qr['id']}",
        headers=h,
        json={"body": "hijack"},
    )
    assert res.status_code == 404
    res = client.delete(
        f"/omnichannel/workspaces/{ws_b}/quick-replies/{qr['id']}", headers=h
    )
    assert res.status_code == 404


def test_quick_reply_unknown_workspace_404(client):
    h = _auth(client)
    res = client.post(
        "/omnichannel/workspaces/does-not-exist/quick-replies",
        headers=h,
        json={"body": "x"},
    )
    assert res.status_code == 404


def test_quick_reply_permission_gate(client, session_factory):
    ws = _default_workspace_id(session_factory)
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="noperm-qr@example.com",
            password=hash_password("noperm1234"),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()

    h = _auth(client, email="noperm-qr@example.com", password="noperm1234")
    assert (
        client.post(
            f"/omnichannel/workspaces/{ws}/quick-replies",
            headers=h,
            json={"body": "x"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/omnichannel/workspaces/{ws}/quick-replies/anything",
            headers=h,
            json={"body": "x"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/omnichannel/workspaces/{ws}/quick-replies/anything", headers=h
        ).status_code
        == 403
    )

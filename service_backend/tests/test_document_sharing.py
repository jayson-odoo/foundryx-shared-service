"""Document sharing tests (plan sprint-3/05 §Phase C, Google-Drive model) —
mapped to the UAT acceptance criteria.

A target has ONE stable share (token never changes); the owner edits
general_access (restricted|workspace|public) + capability + the named-people
list in place. Covers: ensure/update + ceiling/manage gates · stable-link
semantics (flip access keeps the token) · per-person roles · internal/workspace
+ named-people authed access + sign-in-required for anonymous-on-restricted ·
public resolve/state-envelope/uniform-404/password/throttle · folder live-follow
ancestry · public-edit honeypot/sniff/quota/cap + audit + version append ·
cross-tenant guards · file_links seam."""
import uuid

from sqlalchemy.sql import func

from app.config import settings
from app.models import Role, User, UserStatus
from app.models.permission import Permission
from app.models.tenant import DEFAULT_TENANT_ID
from app.security import hash_password
from app.workflow_engine.entity_events import (
    register_event_subscriber,
    unregister_event_subscriber,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%test\n" + b"0" * 64
EXE = b"MZ\x90\x00" + b"\x00" * 64


# ---- helpers ----


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _uniq(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _mkfolder(client, headers, name=None, parent=None):
    res = client.post(
        "/documents/folders",
        json={"name": name or _uniq("Folder"), "parentId": parent},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _upload(client, headers, filename, content, folder_id=None):
    res = client.post(
        "/documents/files",
        files={"file": (filename, content, "application/octet-stream")},
        data={"folder_id": folder_id or ""},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _make_user(session_factory, perm_keys, *, tenant_id=DEFAULT_TENANT_ID):
    db = session_factory()
    email = _uniq("u") + "@example.com"
    password = "Passw0rd!9"
    role = Role(tenant_id=tenant_id, name=_uniq("Role"), description="test", is_system=False)
    if perm_keys:
        role.permissions = db.query(Permission).filter(Permission.key.in_(perm_keys)).all()
    db.add(role)
    db.flush()
    user = User(
        tenant_id=tenant_id, email=email, password=hash_password(password),
        name="Test User", status=UserStatus.ACTIVE.value, email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    uid = user.id
    db.close()
    return email, password, uid


def _headers(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _set_ceiling(client, headers, value):
    res = client.put("/documents/settings", json={"publicSharing": value}, headers=headers)
    assert res.status_code == 200, res.text


def _ensure(client, headers, kind, target_id):
    res = client.post(
        "/documents/shares/ensure",
        json={"targetKind": kind, "targetId": target_id},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _update(client, headers, share_id, **body):
    return client.patch(f"/documents/shares/{share_id}", json=body, headers=headers)


def _share(client, headers, kind, target_id, **body):
    """Ensure the stable share then apply an update; returns the updated share."""
    share = _ensure(client, headers, kind, target_id)
    if body:
        res = _update(client, headers, share["id"], **body)
        assert res.status_code == 200, res.text
        return res.json()
    return share


# ---- ensure / update / stable link ----


def test_ensure_is_idempotent_stable_token(client):
    h = _admin(client)
    f = _upload(client, h, "doc.pdf", PDF)
    a = _ensure(client, h, "file", f["id"])
    b = _ensure(client, h, "file", f["id"])
    assert a["token"] == b["token"]  # one stable link per target
    assert a["generalAccess"] == "restricted"
    # The dialog's get-target returns the same share.
    tgt = client.get(f"/documents/shares/target?kind=file&id={f['id']}", headers=h).json()
    assert tgt and tgt["id"] == a["id"]


def test_flip_access_keeps_same_link(client):
    # Google semantics: change access → SAME token; public loses access on flip.
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view")
    token = share["token"]
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"
    # Flip to restricted — SAME token, now anonymous = sign-in-required.
    flipped = _update(client, h, share["id"], generalAccess="restricted").json()
    assert flipped["token"] == token
    assert client.get(f"/public/documents/{token}").json()["state"] == "sign_in_required"
    # Flip back to public — same token resolves open again.
    _update(client, h, share["id"], generalAccess="public", capability="view")
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"


def test_public_blocked_when_ceiling_off(client):
    h = _admin(client)
    f = _upload(client, h, "doc.pdf", PDF)
    share = _ensure(client, h, "file", f["id"])
    res = _update(client, h, share["id"], generalAccess="public", capability="view")
    assert res.status_code == 403  # ceiling default off


def test_public_edit_clamped_when_view(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _ensure(client, h, "file", f["id"])
    assert _update(client, h, share["id"], generalAccess="public", capability="view").status_code == 200
    assert _update(client, h, share["id"], generalAccess="public", capability="edit").status_code == 403


def test_public_edit_requires_manage(client, session_factory):
    email, pw, _ = _make_user(session_factory, ["documents.read", "documents.share"])
    admin = _admin(client)
    _set_ceiling(client, admin, "edit")
    folder = _mkfolder(client, admin)
    h = _headers(client, email, pw)
    share = _ensure(client, h, "folder", folder["id"])
    res = _update(client, h, share["id"], generalAccess="public", capability="edit")
    assert res.status_code == 403


def test_ensure_requires_share_permission(client, session_factory):
    email, pw, _ = _make_user(session_factory, ["documents.read"])
    admin = _admin(client)
    f = _upload(client, admin, "doc.pdf", PDF)
    h = _headers(client, email, pw)
    res = client.post(
        "/documents/shares/ensure", json={"targetKind": "file", "targetId": f["id"]}, headers=h
    )
    assert res.status_code == 403


def test_people_cross_tenant_rejected(client, session_factory):
    admin = _admin(client)
    operator = _headers(client, "platform@example.com", "platform1234", "platform")
    prov = client.post(
        "/platform/tenants",
        json={"name": "Acme", "slug": _uniq("acme"), "adminName": "Kay",
              "adminEmail": _uniq("kay") + "@acme.com", "adminPassword": "ChangeMe1!"},
        headers=operator,
    ).json()
    _, _, foreign_uid = _make_user(session_factory, [], tenant_id=prov["id"])
    f = _upload(client, admin, "doc.pdf", PDF)
    share = _ensure(client, admin, "file", f["id"])
    res = _update(client, admin, share["id"], people=[{"userId": foreign_uid, "capability": "view"}])
    assert res.status_code == 422


# ---- revoke ----


def test_revoke_then_reensure_reenables_same_token(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view")
    token = share["token"]
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"
    assert client.post("/documents/shares/revoke", json={"ids": [share["id"]]}, headers=h).status_code == 204
    assert client.get(f"/public/documents/{token}").status_code == 404
    # Re-opening the dialog (ensure) re-enables the SAME link (Google) — its
    # prior general_access (public) is preserved, so it resolves open again.
    again = _ensure(client, h, "file", f["id"])
    assert again["token"] == token
    assert again["generalAccess"] == "public"
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"


def test_oversight_one_row_per_target(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view")
    active = client.get("/documents/shares?segment=active", headers=h).json()
    assert sum(1 for s in active["data"] if s["targetId"] == f["id"]) == 1
    client.post("/documents/shares/revoke", json={"ids": [share["id"]]}, headers=h)
    revoked = client.get("/documents/shares?segment=revoked", headers=h).json()
    assert any(s["id"] == share["id"] for s in revoked["data"])


# ---- public resolve ----


def test_public_unknown_token_404(client):
    assert client.get("/public/documents/nope-nope").status_code == 404


def test_public_file_view_and_csp_serve(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view")
    token = share["token"]
    view = client.get(f"/public/documents/{token}").json()
    assert view["state"] == "open" and view["kind"] == "file"
    assert view["file"]["previewKind"] == "pdf"
    res = client.get(f"/public/documents/{token}/file/{f['id']}")
    assert res.status_code == 200
    assert "sandbox" in res.headers.get("content-security-policy", "")
    other = _upload(client, h, "other.pdf", PDF)
    assert client.get(f"/public/documents/{token}/file/{other['id']}").status_code == 404


def test_public_folder_live_follow_and_ancestry(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    root = _mkfolder(client, h, name=_uniq("Shared"))
    sub = _mkfolder(client, h, name=_uniq("Sub"), parent=root["id"])
    inside = _upload(client, h, "inside.pdf", PDF, folder_id=sub["id"])
    outside = _upload(client, h, "outside.pdf", PDF)
    share = _share(client, h, "folder", root["id"], generalAccess="public", capability="view")
    token = share["token"]
    view = client.get(f"/public/documents/{token}").json()
    assert view["kind"] == "folder"
    assert any(x["id"] == sub["id"] for x in view["folders"])
    deep = client.get(f"/public/documents/{token}?folder_id={sub['id']}").json()
    assert any(x["id"] == inside["id"] for x in deep["files"])
    later = _upload(client, h, "later.pdf", PDF, folder_id=sub["id"])
    deep2 = client.get(f"/public/documents/{token}?folder_id={sub['id']}").json()
    assert any(x["id"] == later["id"] for x in deep2["files"])
    assert client.get(f"/public/documents/{token}/file/{inside['id']}").status_code == 200
    assert client.get(f"/public/documents/{token}/file/{outside['id']}").status_code == 404


def test_follow_soft_deleted_path_unreachable(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    root = _mkfolder(client, h)
    sub = _mkfolder(client, h, parent=root["id"])
    inside = _upload(client, h, "inside.pdf", PDF, folder_id=sub["id"])
    share = _share(client, h, "folder", root["id"], generalAccess="public", capability="view")
    token = share["token"]
    assert client.get(f"/public/documents/{token}/file/{inside['id']}").status_code == 200
    client.post("/documents/folders/delete", json={"ids": [sub["id"]]}, headers=h)
    assert client.get(f"/public/documents/{token}/file/{inside['id']}").status_code == 404


def test_ceiling_flip_off_disables_public(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view")
    token = share["token"]
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"
    _set_ceiling(client, h, "off")
    # Public access clamped → anonymous gets sign-in-required (not open).
    assert client.get(f"/public/documents/{token}").json()["state"] == "sign_in_required"
    _set_ceiling(client, h, "view")
    assert client.get(f"/public/documents/{token}").json()["state"] == "open"


def test_password_gate_and_throttle(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_doc_share_max_fails", 2)
    h = _admin(client)
    _set_ceiling(client, h, "view")
    f = _upload(client, h, "doc.pdf", PDF)
    share = _share(client, h, "file", f["id"], generalAccess="public", capability="view", password="s3cret!!")
    token = share["token"]
    assert client.get(f"/public/documents/{token}").json()["state"] == "password_required"
    assert client.post(f"/public/documents/{token}/unlock", json={"password": "x"}).status_code == 403
    assert client.post(f"/public/documents/{token}/unlock", json={"password": "y"}).status_code == 403
    assert client.post(f"/public/documents/{token}/unlock", json={"password": "z"}).status_code == 429
    monkeypatch.setattr(settings, "throttle_doc_share_max_fails", 50)
    ok = client.post(f"/public/documents/{token}/unlock", json={"password": "s3cret!!"})
    assert ok.status_code == 200 and ok.json()["state"] == "open"
    assert client.get(f"/public/documents/{token}/file/{f['id']}").status_code == 403
    served = client.get(
        f"/public/documents/{token}/file/{f['id']}", headers={"X-Share-Password": "s3cret!!"}
    )
    assert served.status_code == 200


# ---- workspace / named-people (authed) ----


def test_workspace_access_and_outsider_and_anon(client, session_factory):
    admin = _admin(client)
    f = _upload(client, admin, "doc.pdf", PDF)
    share = _share(client, admin, "file", f["id"], generalAccess="workspace", capability="view")
    token = share["token"]
    # Any same-tenant member (no special perms) resolves via the authed route.
    email, pw, _ = _make_user(session_factory, [])
    viewer = _headers(client, email, pw)
    res = client.get(f"/documents/shares/by-token/{token}", headers=viewer)
    assert res.status_code == 200 and res.json()["state"] == "open"
    assert res.json()["capability"] == "view"
    assert client.get(f"/documents/shares/by-token/{token}/file/{f['id']}", headers=viewer).status_code == 200
    # Anonymous on a workspace link = sign-in-required (not 404, not open).
    assert client.get(f"/public/documents/{token}").json()["state"] == "sign_in_required"
    # Outsider tenant = 403.
    operator = _headers(client, "platform@example.com", "platform1234", "platform")
    slug = _uniq("acme")
    kay = _uniq("kay") + "@acme.com"
    client.post(
        "/platform/tenants",
        json={"name": "Acme", "slug": slug, "adminName": "Kay", "adminEmail": kay, "adminPassword": "ChangeMe1!"},
        headers=operator,
    )
    outsider = _headers(client, kay, "ChangeMe1!", slug)
    assert client.get(f"/documents/shares/by-token/{token}", headers=outsider).status_code == 403


def test_named_people_per_person_role(client, session_factory):
    admin = _admin(client)
    f = _upload(client, admin, "doc.pdf", PDF)
    e1, p1, uid1 = _make_user(session_factory, [])
    e2, p2, _uid2 = _make_user(session_factory, [])
    # Restricted, one named editor.
    share = _share(
        client, admin, "file", f["id"],
        generalAccess="restricted", capability="view",
        people=[{"userId": uid1, "capability": "edit"}],
    )
    token = share["token"]
    h1 = _headers(client, e1, p1)
    r1 = client.get(f"/documents/shares/by-token/{token}", headers=h1)
    assert r1.status_code == 200 and r1.json()["capability"] == "edit"  # per-person role
    # A non-listed same-tenant user is denied (restricted).
    h2 = _headers(client, e2, p2)
    assert client.get(f"/documents/shares/by-token/{token}", headers=h2).status_code == 403


# ---- shared with me ----


def test_shared_with_me_lists_others_excludes_own(client, session_factory):
    admin = _admin(client)
    f = _upload(client, admin, "shared.pdf", PDF)
    # Admin shares a file with the whole workspace.
    _share(client, admin, "file", f["id"], generalAccess="workspace", capability="view")
    # A different member sees it under "Shared with me".
    email, pw, _ = _make_user(session_factory, [])
    member = _headers(client, email, pw)
    mine = client.get("/documents/shared-with-me", headers=member).json()
    assert any(x["targetId"] == f["id"] and x["name"] == "shared.pdf" for x in mine)
    # The admin (the sharer) does NOT see their own share there.
    admin_list = client.get("/documents/shared-with-me", headers=admin).json()
    assert all(x["targetId"] != f["id"] for x in admin_list)


# ---- public-edit anonymous write ----


def test_public_edit_upload_honeypot_sniff_audit_version(client):
    events = []

    def _sub(db, ev):
        events.append(ev)

    register_event_subscriber(_sub)
    try:
        h = _admin(client)
        _set_ceiling(client, h, "edit")
        folder = _mkfolder(client, h)
        share = _share(client, h, "folder", folder["id"], generalAccess="public", capability="edit")
        token = share["token"]
        url = f"/public/documents/{token}/upload"
        r = client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, data={"company_website": "bot"})
        assert r.status_code == 204
        listing = client.get(f"/documents/folders?folder_id={folder['id']}", headers=h).json()
        assert listing["files"] == []
        assert client.post(url, files={"file": ("x.exe", EXE, "application/octet-stream")}).status_code == 415
        ok = client.post(url, files={"file": ("good.pdf", PDF, "application/pdf")})
        assert ok.status_code == 204
        listing2 = client.get(f"/documents/folders?folder_id={folder['id']}", headers=h).json()
        assert any(x["name"] == "good.pdf" for x in listing2["files"])
    finally:
        unregister_event_subscriber(_sub)
    created = [e for e in events if e["entity_type"] == "file" and e["action"] == "created"]
    assert created and any((e.get("actor") or {}).get("id") == f"share:{token}" for e in created)


def test_public_edit_version_append_on_collision(client):
    h = _admin(client)
    _set_ceiling(client, h, "edit")
    folder = _mkfolder(client, h)
    existing = _upload(client, h, "report.pdf", PDF, folder_id=folder["id"])
    share = _share(client, h, "folder", folder["id"], generalAccess="public", capability="edit")
    url = f"/public/documents/{share['token']}/upload"
    assert client.post(url, files={"file": ("report.pdf", PDF + b"v2", "application/pdf")}).status_code == 204
    versions = client.get(f"/documents/files/{existing['id']}/versions", headers=h).json()
    assert len(versions) == 2


def test_public_edit_per_link_upload_cap(client):
    h = _admin(client)
    _set_ceiling(client, h, "edit")
    folder = _mkfolder(client, h)
    share = _share(
        client, h, "folder", folder["id"], generalAccess="public", capability="edit", maxUploads=1
    )
    url = f"/public/documents/{share['token']}/upload"
    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 204
    assert client.post(url, files={"file": ("b.pdf", PDF, "application/pdf")}).status_code == 409


def test_view_link_upload_denied(client):
    h = _admin(client)
    _set_ceiling(client, h, "view")
    folder = _mkfolder(client, h)
    share = _share(client, h, "folder", folder["id"], generalAccess="public", capability="view")
    assert client.post(
        f"/public/documents/{share['token']}/upload",
        files={"file": ("a.pdf", PDF, "application/pdf")},
    ).status_code == 404


# ---- file_links seam ----


def test_file_links_crud_and_tenant_scope(client):
    h = _admin(client)
    f = _upload(client, h, "doc.pdf", PDF)
    created = client.post(
        "/documents/file-links",
        json={"entityType": "quotation", "entityId": "q-123", "fileId": f["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    link = created.json()
    lst = client.get("/documents/file-links?entity_type=quotation&entity_id=q-123", headers=h).json()
    assert any(x["id"] == link["id"] for x in lst)
    bad = client.post(
        "/documents/file-links",
        json={"entityType": "quotation", "entityId": "q-1", "fileId": str(uuid.uuid4())},
        headers=h,
    )
    assert bad.status_code == 422
    assert client.delete(f"/documents/file-links/{link['id']}", headers=h).status_code == 204

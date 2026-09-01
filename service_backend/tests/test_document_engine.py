"""Document engine tests (plan sprint-3/04 §Phase C) - service/router over the
httpx TestClient, mapped to the UAT acceptance criteria.

Covers: navigation + breadcrumb (AC-NAV) · folder create/rename/move + cycle
guard (AC-FOLDER, FOLDER-E1) · upload happy path + versions (AC-UPLOAD-01/05) ·
collision 409 + replace→version + keep-both rename (AC-UPLOAD-06/07/08) · sniff
hard-floor exe/html/svg (AC-UPLOAD-09) · type/size policy + quota 413
(AC-UPLOAD-10/11) · soft-delete cascade + trash + restore + purge (AC-TRASH) ·
ZIP job (AC-DOWNLOAD-02) · CSP-sandbox content serve (AC-PREVIEW-02) · types CRUD
(AC-TYPE) · settings + quota (AC-SETTINGS) · file workflow-event emit (AC-EVENT)
· tenant isolation (X-E4) · auth gate (AC-PERM)."""
import uuid

from app.models.tenant import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%test\n" + b"0" * 64
TEXT = b"hello,world\nfoo,bar\n"
EXE = b"MZ\x90\x00" + b"\x00" * 64
HTML = b"<!doctype html><html><body>x</body></html>"
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


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


def _upload(client, headers, filename, content, folder_id=None, on_conflict=None, type_id=None):
    data = {"folder_id": folder_id or ""}
    if on_conflict:
        data["on_conflict"] = on_conflict
    if type_id:
        data["attachment_type_id"] = type_id
    return client.post(
        "/documents/files",
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
        headers=headers,
    )


# ---- navigation + folders ----


def test_root_lists_then_create_and_nest(client):
    h = _admin(client)
    root = client.get("/documents/folders", headers=h)
    assert root.status_code == 200, root.text
    assert root.json()["breadcrumb"] == []

    parent = _mkfolder(client, h, "Quotations")
    child = _mkfolder(client, h, "2026", parent=parent["id"])

    listing = client.get(f"/documents/folders?folder_id={parent['id']}", headers=h).json()
    assert listing["folder"]["name"] == "Quotations"
    assert any(f["id"] == child["id"] for f in listing["folders"])
    # breadcrumb resolves root → current
    deep = client.get(f"/documents/folders?folder_id={child['id']}", headers=h).json()
    assert [c["name"] for c in deep["breadcrumb"]] == ["Quotations", "2026"]


def test_rename_folder_and_file(client):
    h = _admin(client)
    folder = _mkfolder(client, h)
    r = client.patch(f"/documents/folders/{folder['id']}", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"

    up = _upload(client, h, "doc.pdf", PDF, folder_id=folder["id"]).json()
    rf = client.patch(f"/documents/files/{up['id']}", json={"name": "new.pdf"}, headers=h)
    assert rf.status_code == 200
    assert rf.json()["id"] == up["id"] and rf.json()["name"] == "new.pdf"


def test_move_file_and_folder_cycle_guard(client):
    h = _admin(client)
    a = _mkfolder(client, h, "A")
    b = _mkfolder(client, h, "B", parent=a["id"])
    up = _upload(client, h, "x.pdf", PDF).json()

    mv = client.post(
        "/documents/files/move", json={"ids": [up["id"]], "targetFolderId": a["id"]}, headers=h
    )
    assert mv.status_code == 204
    inA = client.get(f"/documents/folders?folder_id={a['id']}", headers=h).json()
    assert any(f["id"] == up["id"] for f in inA["files"])

    # Move A into its own descendant B → cycle → 422.
    cyc = client.post(
        "/documents/folders/move", json={"ids": [a["id"]], "targetFolderId": b["id"]}, headers=h
    )
    assert cyc.status_code == 422


# ---- upload + versioning + collision ----


def test_upload_creates_version_and_lists(client):
    h = _admin(client)
    f = _mkfolder(client, h)
    res = _upload(client, h, "image.png", PNG, folder_id=f["id"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "image.png" and body["versionCount"] == 1
    assert body["currentVersion"]["sizeBytes"] == len(PNG)
    vers = client.get(f"/documents/files/{body['id']}/versions", headers=h).json()
    assert len(vers) == 1


def test_collision_then_replace_and_keep_both(client):
    h = _admin(client)
    f = _mkfolder(client, h)
    _upload(client, h, "dup.pdf", PDF, folder_id=f["id"])

    clash = _upload(client, h, "dup.pdf", PDF, folder_id=f["id"])
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert detail["fileName"] == "dup.pdf" and detail["existingFileId"]

    replaced = _upload(client, h, "dup.pdf", PDF + b"more", folder_id=f["id"], on_conflict="replace")
    assert replaced.status_code == 201 and replaced.json()["versionCount"] == 2

    kept = _upload(client, h, "dup.pdf", PDF, folder_id=f["id"], on_conflict="keep_both")
    assert kept.status_code == 201 and kept.json()["name"] == "dup (1).pdf"


def test_sniff_floor_blocks_dangerous_types(client):
    h = _admin(client)
    for name, content in [("m.exe", EXE), ("p.html", HTML), ("v.svg", SVG)]:
        res = _upload(client, h, name, content)
        assert res.status_code == 415, f"{name} should be rejected: {res.status_code}"
    # ...but a real document type passes.
    assert _upload(client, h, "ok.txt", TEXT).status_code == 201


def test_type_policy_and_quota(client):
    h = _admin(client)
    # A type capped at 1 MB accepting only pdf.
    t = client.post(
        "/documents/types",
        json={"name": _uniq("Doc"), "allowedExts": ["pdf"], "maxMb": 1},
        headers=h,
    ).json()
    big = _upload(client, h, "big.pdf", b"%PDF-" + b"0" * (2 * 1024 * 1024), type_id=t["id"])
    assert big.status_code == 415  # over the 1 MB type cap
    wrong = _upload(client, h, "note.txt", TEXT, type_id=t["id"])
    assert wrong.status_code == 415  # .txt not allowed by the pdf-only type

    # Quota: shrink to ~0 and confirm the next upload is blocked (413).
    client.put("/documents/settings", json={"storageQuotaMb": 0}, headers=h)
    blocked = _upload(client, h, "q.pdf", PDF)
    assert blocked.status_code == 413
    client.put("/documents/settings", json={"storageQuotaMb": 4096}, headers=h)


# ---- trash ----


def test_soft_delete_cascade_restore_purge(client):
    h = _admin(client)
    parent = _mkfolder(client, h, "Parent")
    child = _mkfolder(client, h, "Child", parent=parent["id"])
    inside = _upload(client, h, "inside.pdf", PDF, folder_id=child["id"]).json()

    assert client.post("/documents/folders/delete", json={"ids": [parent["id"]]}, headers=h).status_code == 204
    # Gone from the Drive, present in Trash with the subtree cascaded.
    trash = client.get("/documents/trash", headers=h).json()
    tf = {f["id"] for f in trash["folders"]}
    assert parent["id"] in tf and child["id"] in tf
    assert inside["id"] in {f["id"] for f in trash["files"]}

    assert client.post("/documents/folders/restore", json={"ids": [parent["id"]]}, headers=h).status_code == 204
    back = client.get("/documents/folders", headers=h).json()
    assert parent["id"] in {f["id"] for f in back["folders"]}

    # Purge removes it permanently.
    client.post("/documents/folders/delete", json={"ids": [parent["id"]]}, headers=h)
    assert client.post("/documents/folders/purge", json={"ids": [parent["id"]]}, headers=h).status_code == 204
    trash2 = client.get("/documents/trash", headers=h).json()
    assert parent["id"] not in {f["id"] for f in trash2["folders"]}


def test_quota_counts_trashed_blobs(client):
    # Code-review fix: trashed (not purged) files still occupy storage, so they
    # must count toward the quota - else trash-then-upload bypasses it.
    h = _admin(client)
    client.put("/documents/settings", json={"storageQuotaMb": 2}, headers=h)
    blob = b"%PDF-" + b"0" * 1_400_000  # ~1.4 MB
    f1 = _upload(client, h, "a.pdf", blob)
    assert f1.status_code in (200, 201), f1.text
    client.post("/documents/files/delete", json={"ids": [f1.json()["id"]]}, headers=h)
    # Second 1.4 MB upload: 1.4 (trashed) + 1.4 > 2 MB quota → 413.
    blocked = _upload(client, h, "b.pdf", blob)
    assert blocked.status_code == 413
    client.put("/documents/settings", json={"storageQuotaMb": 4096}, headers=h)


def test_restore_recollision_renames(client):
    # Code-review fix (plan D9): restoring a file whose name was re-used while it
    # sat in Trash must rename the restored copy, never create two live siblings.
    h = _admin(client)
    a = _upload(client, h, "dup.pdf", PDF).json()
    client.post("/documents/files/delete", json={"ids": [a["id"]]}, headers=h)
    _upload(client, h, "dup.pdf", PDF)  # new live file, same name (old is trashed)
    assert client.post("/documents/files/restore", json={"ids": [a["id"]]}, headers=h).status_code == 204
    names = [f["name"] for f in client.get("/documents/folders", headers=h).json()["files"]]
    assert names.count("dup.pdf") == 1
    assert "dup (1).pdf" in names


def test_content_disposition_header_is_sanitized(client):
    # Code-review fix: a quote/CRLF in the file name must not break out of the
    # Content-Disposition header.
    h = _admin(client)
    f = _upload(client, h, 'ev"il.pdf', PDF).json()
    res = client.get(f"/documents/files/{f['id']}/content", headers=h)
    cd = res.headers["content-disposition"]
    # The ASCII fallback filename carries no raw quote; the real name rides
    # filename* (percent-encoded).
    ascii_part = cd.split("filename*", 1)[0]
    assert '"' not in ascii_part.split('filename="', 1)[1].rstrip('"; ')
    assert "filename*=UTF-8''" in cd


# ---- download jobs ----


def test_zip_job_runs_eager_to_ready(client):
    h = _admin(client)
    f = _mkfolder(client, h, "Bundle")
    _upload(client, h, "a.pdf", PDF, folder_id=f["id"])
    _upload(client, h, "b.txt", TEXT, folder_id=f["id"])

    job = client.post("/documents/download-jobs", json={"folderIds": [f["id"]]}, headers=h)
    assert job.status_code == 201, job.text
    body = job.json()
    assert body["fileCount"] == 2 and body["status"] == "ready"

    jobs = client.get("/documents/download-jobs", headers=h).json()
    assert any(j["id"] == body["id"] for j in jobs)
    # The ready ZIP streams.
    content = client.get(f"/documents/download-jobs/{body['id']}/content", headers=h)
    assert content.status_code == 200
    assert content.content[:2] == b"PK"  # zip magic


# ---- content serve ----


def test_content_serve_is_sandboxed(client):
    h = _admin(client)
    up = _upload(client, h, "pic.png", PNG).json()
    res = client.get(f"/documents/files/{up['id']}/content?disposition=inline", headers=h)
    assert res.status_code == 200
    assert res.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "private" in res.headers["cache-control"]


# ---- attachment types ----


def test_types_crud(client):
    h = _admin(client)
    created = client.post(
        "/documents/types",
        json={"name": _uniq("Sheet"), "description": "x", "allowedExts": [".XLSX", "csv"], "maxMb": 15},
        headers=h,
    ).json()
    # Extensions normalise (dot-less, lowercase).
    assert sorted(created["allowedExts"]) == ["csv", "xlsx"]
    upd = client.patch(f"/documents/types/{created['id']}", json={"maxMb": 20}, headers=h).json()
    assert upd["maxMb"] == 20
    lst = client.get("/documents/types", headers=h).json()
    assert any(t["id"] == created["id"] for t in lst["data"])
    assert client.delete(f"/documents/types/{created['id']}", headers=h).status_code == 204


# ---- settings ----


def test_settings_roundtrip_and_usage(client):
    h = _admin(client)
    _upload(client, h, "u.pdf", PDF)
    s = client.get("/documents/settings", headers=h).json()
    assert s["usedBytes"] >= len(PDF)
    saved = client.put(
        "/documents/settings",
        json={"defaultMaxFileMb": 25, "storageQuotaMb": None, "publicSharing": "view"},
        headers=h,
    ).json()
    assert saved["defaultMaxFileMb"] == 25 and saved["storageQuotaMb"] is None
    assert saved["publicSharing"] == "view"


# ---- workflow event seam ----


def test_upload_emits_file_event(client):
    from app.workflow_engine.entity_events import (
        register_event_subscriber,
        unregister_event_subscriber,
    )

    captured = []

    def sub(_session, event):
        if event.get("entity_type") == "file":
            captured.append(event)

    register_event_subscriber(sub)
    try:
        h = _admin(client)
        _upload(client, h, "evt.pdf", PDF)
    finally:
        unregister_event_subscriber(sub)
    assert any(e["action"] == "created" for e in captured)


# ---- tenant isolation + auth ----


def test_unauthenticated_is_blocked(client):
    res = client.get("/documents/folders")
    assert res.status_code in (401, 403)


def test_tenant_isolation(session_factory):
    from app.services.document_service import DocumentService

    db = session_factory()
    try:
        svc = DocumentService(db)
        # A folder for the default tenant.
        f = svc.create_folder(DEFAULT_TENANT_ID, None, "Secret", _FakeUser("u1"))
        # Another tenant sees an empty Drive (never the default tenant's data).
        other = svc.list_folder("tenant-other", None)
        assert all(fl.id != f.id for fl in other.folders)
        assert other.files == []
    finally:
        db.close()


class _FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.name = "Test"
        self.email = "t@example.com"

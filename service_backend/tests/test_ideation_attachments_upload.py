"""Ideation attachment upload + serve (plan 15 B1, AC-15-14..19).

Operator + embed upload of a file onto an idea: sniff-first (magic bytes, the
declared type is ignored), 25 MB capped read, stored through the tenant storage,
served CSP-sandboxed + nosniff. Tenant scoped on every stored-id lookup.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_br import _make_user, _product
from tests.test_ideation_embed_writes import (
    _auth,
    _bearer,
    _insert_idea,
    _mint,
    _seed_connection,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
HTML = b"<html><script>alert(1)</script></html>"
EXE = b"MZ" + b"\x90\x00" * 32
CAP = 25 * 1024 * 1024


@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def media_root(tmp_path):
    from app.services.storage import clear_adapter_cache

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    clear_adapter_cache()
    try:
        yield tmp_path
    finally:
        settings.media_root = prev
        clear_adapter_cache()


@pytest.fixture
def ctx(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid)
    return {"c": ideation_client, "h": h, "pid": pid, "idea_id": idea_id}


def _upload(c, h, idea_id, content, name="f.bin", prefix="/ideation"):
    return c.post(
        f"{prefix}/ideas/{idea_id}/attachments",
        headers=h,
        files={"file": (name, content, "application/octet-stream")},
    )


# ── AC-15-14/16/19: upload happy paths ───────────────────────────────────────
@pytest.mark.parametrize(
    "content,kind,name",
    [(PNG, "image", "shot.png"), (OGG, "audio", "note.ogg"), (PDF, "file", "spec.pdf")],
    ids=["png", "ogg", "pdf"],
)
def test_upload_returns_201_with_kind_and_content_path(ctx, content, kind, name):
    res = _upload(ctx["c"], ctx["h"], ctx["idea_id"], content, name=name)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == kind
    assert body["name"] == name
    assert body["sizeBytes"] == len(content)
    aid = body["id"]
    assert body["contentPath"] == f"/ideation/ideas/{ctx['idea_id']}/attachments/{aid}/content"
    assert body["url"] == ""


def test_upload_persists_row_fields(ctx):
    from modules.ideation.models import IdeaAttachment

    res = _upload(ctx["c"], ctx["h"], ctx["idea_id"], PNG, name="shot.png")
    aid = res.json()["id"]
    db = ctx["c"]._factory()
    try:
        row = db.query(IdeaAttachment).filter(IdeaAttachment.id == aid).one()
        assert row.storage_key
        assert row.source_msg_id == f"upload:{aid}"
        assert row.mime == "image/png"
        assert row.size_bytes == len(PNG)
        assert row.tenant_id == DEFAULT_TENANT_ID
    finally:
        db.close()


def test_detail_lists_uploaded_attachment(ctx):
    aid = _upload(ctx["c"], ctx["h"], ctx["idea_id"], PNG, name="shot.png").json()["id"]
    detail = ctx["c"].get(f"/ideation/ideas/{ctx['idea_id']}", headers=ctx["h"])
    assert detail.status_code == 200, detail.text
    assert aid in [a["id"] for a in detail.json()["attachments"]]


# ── AC-15-16: serve headers ──────────────────────────────────────────────────
def test_content_served_sandboxed(ctx):
    aid = _upload(ctx["c"], ctx["h"], ctx["idea_id"], PNG, name="shot.png").json()["id"]
    res = ctx["c"].get(
        f"/ideation/ideas/{ctx['idea_id']}/attachments/{aid}/content", headers=ctx["h"]
    )
    assert res.status_code == 200, res.text
    assert res.content == PNG
    assert res.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "private" in res.headers["cache-control"]


# ── AC-15-16: sniff + cap ────────────────────────────────────────────────────
@pytest.mark.parametrize("content,name", [(HTML, "x.png"), (EXE, "x.pdf")], ids=["html", "exe"])
def test_unverifiable_type_is_415(ctx, content, name):
    res = _upload(ctx["c"], ctx["h"], ctx["idea_id"], content, name=name)
    assert res.status_code == 415, res.text


def test_oversize_body_is_413(ctx):
    res = _upload(ctx["c"], ctx["h"], ctx["idea_id"], PNG + b"\x00" * CAP, name="big.png")
    assert res.status_code == 413, res.text


def test_upload_to_missing_idea_is_404(ctx):
    # Control: the same upload to a real idea succeeds, so the 404 is the idea lookup.
    assert _upload(ctx["c"], ctx["h"], ctx["idea_id"], PNG, name="a.png").status_code == 201
    res = _upload(ctx["c"], ctx["h"], "no-such-idea", PNG, name="a.png")
    assert res.status_code == 404, res.text


# ── AC-15-18: permission + tenant scope ──────────────────────────────────────
def test_upload_without_triage_manage_is_403(ctx):
    _make_user(ctx["c"]._factory, "viewer@x.com", "viewer1234", ["ideation.ideas.view"])
    h = _auth(ctx["c"], email="viewer@x.com", password="viewer1234")
    res = _upload(ctx["c"], h, ctx["idea_id"], PNG, name="a.png")
    assert res.status_code == 403, res.text


def test_cross_tenant_attachment_id_is_404(ctx):
    from modules.ideation.models import IdeaAttachment

    foreign_idea = _insert_idea(ctx["c"]._factory, ctx["pid"], tenant_id="tenant-x")
    db = ctx["c"]._factory()
    try:
        row = IdeaAttachment(
            tenant_id="tenant-x",
            idea_id=foreign_idea,
            source_msg_id="upload:foreign",
            kind="image",
            url="",
            filename="f.png",
            storage_key="ideation/ideas/x/y",
            mime="image/png",
            size_bytes=3,
        )
        db.add(row)
        db.commit()
        foreign_aid = row.id
    finally:
        db.close()
    # Foreign attachment id under our own idea, and under the foreign idea.
    for iid in (ctx["idea_id"], foreign_idea):
        res = ctx["c"].get(
            f"/ideation/ideas/{iid}/attachments/{foreign_aid}/content", headers=ctx["h"]
        )
        assert res.status_code == 404, res.text


# ── embed upload + serve ─────────────────────────────────────────────────────
def test_embed_upload_and_serve(ideation_client):
    c = ideation_client
    h = _auth(c)
    pid = _product(c, h)
    _seed_connection(c._factory, product_id=pid)
    idea_id = _insert_idea(c._factory, pid)
    eh = _bearer(_mint(c))
    res = _upload(c, eh, idea_id, PNG, name="shot.png", prefix="/embed")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["contentPath"].startswith("/embed/ideas/")
    got = c.get(body["contentPath"], headers=eh)
    assert got.status_code == 200, got.text
    assert got.headers["x-content-type-options"] == "nosniff"


def test_embed_upload_outside_product_scope_is_404(ideation_client):
    c = ideation_client
    h = _auth(c)
    pid = _product(c, h, name="Product A")
    other = _product(c, h, name="Product B")
    _seed_connection(c._factory, product_id=pid)
    foreign_idea = _insert_idea(c._factory, other)
    in_scope = _insert_idea(c._factory, pid)
    eh = _bearer(_mint(c))
    # Control: the in-scope idea accepts the upload, so the 404 below is the scope check.
    assert _upload(c, eh, in_scope, PNG, name="ok.png", prefix="/embed").status_code == 201
    res = _upload(c, eh, foreign_idea, PNG, name="a.png", prefix="/embed")
    assert res.status_code == 404, res.text


# ── AC-15-17: storage location registered ────────────────────────────────────
def test_idea_attachment_storage_key_registered():
    from app.storage_migration.registry import registered_scalar_columns
    from modules.ideation.bootstrap import register_engine_entities

    register_engine_entities()
    assert ("idea_attachments", "storage_key") in registered_scalar_columns()

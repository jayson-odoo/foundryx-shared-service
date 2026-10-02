"""Plan 19 - idea comments (AC-19-01..11), RED tests written before the code.

Operator routes: ``/ideation/ideas/{id}/comments`` (GET/POST) and
``/ideation/ideas/{id}/comments/{commentId}`` (PATCH/DELETE). Embed twins under
``/embed/ideas/...``. New permission ``ideation.ideas.comment`` swept to every
``ideation.ideas.upvote`` holder. Every test seeds its own idea / users.
"""
import pytest
from sqlalchemy import text

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_br import _make_user  # noqa: F401
from tests.test_ideation_embed_writes import (  # noqa: F401
    _auth,
    _bearer,
    _create_software_product,
    _insert_idea,
    _mint,
    _seed_connection,
    ideation_client,
)

COMMENT = "ideation.ideas.comment"
VIEW = "ideation.ideas.view"
UPVOTE = "ideation.ideas.upvote"
MANAGE = "ideation.triage.manage"


# ── helpers ───────────────────────────────────────────────────────────────────
def _url(idea_id, comment_id=None, prefix="/ideation"):
    base = f"{prefix}/ideas/{idea_id}/comments"
    return f"{base}/{comment_id}" if comment_id else base


def _post(client, h, idea_id, body="hello", parent_id=None, prefix="/ideation"):
    payload = {"body": body}
    if parent_id is not None:
        payload["parentId"] = parent_id
    return client.post(_url(idea_id, prefix=prefix), headers=h, json=payload)


def _listed(client, h, idea_id, prefix="/ideation"):
    res = client.get(_url(idea_id, prefix=prefix), headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def _user_h(client, email, perms):
    _make_user(client._factory, email, "pw-1234-abc", perms)
    return _auth(client, email=email, password="pw-1234-abc")


@pytest.fixture
def op(ideation_client):
    """Admin headers + a product + one in-tenant idea."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea = _insert_idea(ideation_client._factory, pid, problem="idea for comments")
    return {"c": ideation_client, "h": h, "pid": pid, "idea": idea}


# ── AC-19-01 ──────────────────────────────────────────────────────────────────
def test_ac_19_01_idea_comment_model_columns(ideation_client):
    from modules.ideation.models import IdeaComment

    cols = set(IdeaComment.__table__.columns.keys())
    assert {
        "id", "tenant_id", "idea_id", "parent_id", "author_kind", "author_id",
        "author_name", "body", "created_at", "edited_at", "deleted_at",
    } <= cols
    assert IdeaComment.__tablename__ == "idea_comments"


def test_ac_19_01_migration_file_exists():
    from pathlib import Path

    p = (
        Path(__file__).resolve().parent.parent
        / "modules/ideation/alembic/versions/0015_ideation_idea_comments.py"
    )
    assert p.exists(), p
    src = p.read_text()
    assert "0015_ideation_idea_comments" in src
    assert "0014_ideation_br_build" in src
    assert "IF NOT EXISTS" in src.upper()


# ── AC-19-02 / 03 ─────────────────────────────────────────────────────────────
def test_ac_19_02_list_empty_then_oldest_first_with_shape(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    assert _listed(c, h, idea) == []
    first = _post(c, h, idea, "first")
    assert first.status_code == 201, first.text
    second = _post(c, h, idea, "second")
    assert second.status_code == 201, second.text
    rows = _listed(c, h, idea)
    assert [r["body"] for r in rows] == ["first", "second"]  # oldest first
    assert set(rows[0]) >= {
        "id", "ideaId", "parentId", "authorName", "authorKind", "body",
        "isDeleted", "isMine", "canEdit", "canDelete", "createdAt", "editedAt",
    }
    assert rows[0]["ideaId"] == idea
    assert rows[0]["parentId"] is None
    assert rows[0]["authorKind"] == "user"
    assert rows[0]["isDeleted"] is False
    assert rows[0]["editedAt"] is None
    assert rows[0]["createdAt"].endswith("Z")
    assert "authorId" not in rows[0] and "author_id" not in rows[0]  # never on the wire


def test_ac_19_02_cross_tenant_idea_404(op):
    other = _insert_idea(
        op["c"]._factory, op["pid"], problem="foreign", tenant_id="tenant-x"
    )
    assert op["c"].get(_url(other), headers=op["h"]).status_code == 404
    assert _post(op["c"], op["h"], other).status_code == 404


def test_ac_19_02_list_requires_view_permission(op):
    h = _user_h(op["c"], "noperm@example.com", set())
    assert op["c"].get(_url(op["idea"]), headers=h).status_code == 403


def test_ac_19_03_create_author_and_strip(op):
    res = _post(op["c"], op["h"], op["idea"], "  padded body  ")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["body"] == "padded body"
    assert body["authorKind"] == "user"
    assert body["authorName"]
    assert body["isMine"] is True


def test_ac_19_03_author_name_falls_back_to_email(op):
    c = op["c"]
    h = _user_h(c, "noname@example.com", {VIEW, COMMENT})
    from app.models import User

    db = c._factory()
    try:
        u = db.query(User).filter(User.email == "noname@example.com").one()
        u.name = None
        db.commit()
    finally:
        db.close()
    res = _post(c, h, op["idea"], "who am i")
    assert res.status_code == 201, res.text
    assert res.json()["authorName"] == "noname@example.com"


@pytest.mark.parametrize("bad", ["", "   \n ", "x" * 5001])
def test_ac_19_03_create_body_validation_422(op, bad):
    assert _post(op["c"], op["h"], op["idea"], bad).status_code == 422


def test_ac_19_03_max_length_5000_ok(op):
    assert _post(op["c"], op["h"], op["idea"], "x" * 5000).status_code == 201


def test_ac_19_03_create_requires_comment_permission(op):
    h = _user_h(op["c"], "viewonly@example.com", {VIEW, UPVOTE})
    assert _post(op["c"], h, op["idea"]).status_code == 403


# ── AC-19-04 ──────────────────────────────────────────────────────────────────
def test_ac_19_04_reply_to_reply_normalised_to_top_level(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    top = _post(c, h, idea, "top").json()
    reply = _post(c, h, idea, "reply", parent_id=top["id"])
    assert reply.status_code == 201, reply.text
    assert reply.json()["parentId"] == top["id"]
    nested = _post(c, h, idea, "nested", parent_id=reply.json()["id"])
    assert nested.status_code == 201, nested.text
    assert nested.json()["parentId"] == top["id"]  # never a third level


def test_ac_19_04_parent_from_other_idea_or_tenant_404(op):
    c, h = op["c"], op["h"]
    idea_b = _insert_idea(c._factory, op["pid"], problem="idea b")
    foreign_parent = _post(c, h, idea_b, "on b").json()["id"]
    res = _post(c, h, op["idea"], "cross", parent_id=foreign_parent)
    assert res.status_code == 404, res.text
    assert _listed(c, h, op["idea"]) == []  # nothing attached
    assert _post(c, h, op["idea"], "x", parent_id="nope").status_code == 404


# ── AC-19-05 ──────────────────────────────────────────────────────────────────
def test_ac_19_05_edit_own_sets_edited_at(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "before").json()["id"]
    res = c.patch(_url(idea, cid), headers=h, json={"body": "  after "})
    assert res.status_code == 200, res.text
    assert res.json()["body"] == "after"
    assert res.json()["editedAt"] is not None
    assert _listed(c, h, idea)[0]["editedAt"] is not None


def test_ac_19_05_edit_by_other_user_403_even_for_manager(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "mine").json()["id"]
    other = _user_h(c, "other@example.com", {VIEW, COMMENT, MANAGE})
    res = c.patch(_url(idea, cid), headers=other, json={"body": "hijack"})
    assert res.status_code == 403, res.text
    assert _listed(c, h, idea)[0]["body"] == "mine"


@pytest.mark.parametrize("bad", ["", "  ", "y" * 5001])
def test_ac_19_05_edit_validation_422(op, bad):
    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "ok").json()["id"]
    assert c.patch(_url(idea, cid), headers=h, json={"body": bad}).status_code == 422


def test_ac_19_05_edit_deleted_comment_404(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "gone").json()["id"]
    assert c.delete(_url(idea, cid), headers=h).status_code == 204
    assert c.patch(_url(idea, cid), headers=h, json={"body": "x"}).status_code == 404


def test_ac_19_05_edit_comment_of_other_idea_404(op):
    c, h = op["c"], op["h"]
    idea_b = _insert_idea(c._factory, op["pid"], problem="b")
    cid = _post(c, h, idea_b, "on b").json()["id"]
    assert c.patch(_url(op["idea"], cid), headers=h, json={"body": "x"}).status_code == 404


# ── AC-19-06 ──────────────────────────────────────────────────────────────────
def test_ac_19_06_author_deletes_own(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "bye").json()["id"]
    assert c.delete(_url(idea, cid), headers=h).status_code == 204
    assert _listed(c, h, idea) == []  # no live replies -> omitted


def test_ac_19_06_triage_manager_deletes_others(op):
    c, idea = op["c"], op["idea"]
    author = _user_h(c, "author@example.com", {VIEW, COMMENT})
    cid = _post(c, author, idea, "mine").json()["id"]
    mod = _user_h(c, "mod@example.com", {VIEW, MANAGE})
    assert c.delete(_url(idea, cid), headers=mod).status_code == 204
    assert _listed(c, op["h"], idea) == []


def test_ac_19_06_plain_user_cannot_delete_others_403(op):
    c, idea = op["c"], op["idea"]
    cid = _post(c, op["h"], idea, "admin's").json()["id"]
    plain = _user_h(c, "plain@example.com", {VIEW, COMMENT})
    assert c.delete(_url(idea, cid), headers=plain).status_code == 403
    assert len(_listed(c, op["h"], idea)) == 1


def test_ac_19_06_deleted_with_live_replies_is_placeholder(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    top = _post(c, h, idea, "top secret").json()["id"]
    _post(c, h, idea, "reply", parent_id=top)
    assert c.delete(_url(idea, top), headers=h).status_code == 204
    rows = _listed(c, h, idea)
    assert len(rows) == 2
    placeholder = next(r for r in rows if r["id"] == top)
    assert placeholder["isDeleted"] is True
    assert placeholder["body"] is None
    assert placeholder["authorName"] is None
    assert placeholder["canEdit"] is False and placeholder["canDelete"] is False


def test_ac_19_06_deleted_parent_omitted_once_last_reply_deleted(op):
    c, h, idea = op["c"], op["h"], op["idea"]
    top = _post(c, h, idea, "top").json()["id"]
    rep = _post(c, h, idea, "reply", parent_id=top).json()["id"]
    c.delete(_url(idea, top), headers=h)
    assert len(_listed(c, h, idea)) == 2
    assert c.delete(_url(idea, rep), headers=h).status_code == 204
    assert _listed(c, h, idea) == []


def test_ac_19_06_delete_unknown_404(op):
    assert op["c"].delete(_url(op["idea"], "nope"), headers=op["h"]).status_code == 404


def test_ac_19_06_soft_delete_keeps_row(op):
    from modules.ideation.models import IdeaComment

    c, h, idea = op["c"], op["h"], op["idea"]
    cid = _post(c, h, idea, "soft").json()["id"]
    c.delete(_url(idea, cid), headers=h)
    db = c._factory()
    try:
        row = db.get(IdeaComment, cid)
        assert row is not None and row.deleted_at is not None
    finally:
        db.close()


# ── AC-19-07 ──────────────────────────────────────────────────────────────────
def test_ac_19_07_flags_per_caller(op):
    c, idea = op["c"], op["idea"]
    author = _user_h(c, "a1@example.com", {VIEW, COMMENT})
    _post(c, author, idea, "by a1")

    as_author = _listed(c, author, idea)[0]
    assert (as_author["isMine"], as_author["canEdit"], as_author["canDelete"]) == (True, True, True)

    peer = _user_h(c, "peer@example.com", {VIEW, COMMENT})
    as_peer = _listed(c, peer, idea)[0]
    assert (as_peer["isMine"], as_peer["canEdit"], as_peer["canDelete"]) == (False, False, False)

    mod = _user_h(c, "mod2@example.com", {VIEW, MANAGE})
    as_mod = _listed(c, mod, idea)[0]
    assert (as_mod["isMine"], as_mod["canEdit"], as_mod["canDelete"]) == (False, False, True)


# ── AC-19-08 ──────────────────────────────────────────────────────────────────
def test_ac_19_08_merged_child_refuses_create_edit_but_reads(op):
    from modules.ideation.models import Idea

    c, h, idea = op["c"], op["h"], op["idea"]
    survivor = _insert_idea(c._factory, op["pid"], problem="survivor")
    cid = _post(c, h, idea, "before merge").json()["id"]
    db = c._factory()
    try:
        row = db.get(Idea, idea)
        row.merged_into_id = survivor
        db.commit()
    finally:
        db.close()
    assert _post(c, h, idea, "after").status_code == 409
    assert c.patch(_url(idea, cid), headers=h, json={"body": "x"}).status_code == 409
    assert [r["body"] for r in _listed(c, h, idea)] == ["before merge"]


# ── AC-19-09 ──────────────────────────────────────────────────────────────────
def test_ac_19_09_idea_delete_removes_comments(op):
    from modules.ideation.models import IdeaComment

    c, h, idea = op["c"], op["h"], op["idea"]
    top = _post(c, h, idea, "top").json()["id"]
    _post(c, h, idea, "reply", parent_id=top)
    res = c.delete(f"/ideation/ideas/{idea}", headers=h)
    assert res.status_code in (200, 204), res.text
    db = c._factory()
    try:
        assert db.query(IdeaComment).filter(IdeaComment.idea_id == idea).count() == 0
    finally:
        db.close()


# ── AC-19-10 embed ────────────────────────────────────────────────────────────
@pytest.fixture
def emb(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h, name="Product A")
    other_pid = _create_software_product(ideation_client, h, name="Product B")
    _seed_connection(ideation_client._factory, product_id=pid)
    f = ideation_client._factory
    return {
        "c": ideation_client,
        "h": h,
        "idea": _insert_idea(f, pid, problem="in scope"),
        "other_product": _insert_idea(f, other_pid, problem="other product"),
        "other_tenant": _insert_idea(f, pid, problem="other tenant", tenant_id="tenant-x"),
        "bearer": _bearer(_mint(ideation_client, sub="user-1")),
        "bearer2": _bearer(_mint(ideation_client, sub="user-2")),
    }


def test_ac_19_10_embed_crud_happy_path(emb):
    c, idea, b = emb["c"], emb["idea"], emb["bearer"]
    created = _post(c, b, idea, "from portal", prefix="/embed")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["authorKind"] == "embed"
    assert body["authorName"] == "a@sorento.my"  # the token's email claim
    assert body["isMine"] is True and body["canEdit"] is True and body["canDelete"] is True
    cid = body["id"]

    listed = _listed(c, b, idea, prefix="/embed")
    assert [r["body"] for r in listed] == ["from portal"]
    assert "authorId" not in listed[0]

    edited = c.patch(_url(idea, cid, "/embed"), headers=b, json={"body": "edited"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["editedAt"] is not None

    assert c.delete(_url(idea, cid, "/embed"), headers=b).status_code == 204
    assert _listed(c, b, idea, prefix="/embed") == []


def test_ac_19_10_embed_author_id_is_voter_id(emb):
    from modules.ideation.models import IdeaComment

    cid = _post(emb["c"], emb["bearer"], emb["idea"], "x", prefix="/embed").json()["id"]
    db = emb["c"]._factory()
    try:
        row = db.get(IdeaComment, cid)
        assert row.author_kind == "embed"
        assert row.author_id == "embed-user:user-1"
    finally:
        db.close()


def test_ac_19_10_embed_author_name_falls_back_to_portal_user(ideation_client):
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    from app.config import settings
    from tests.test_ideation_embed_writes import AUD, CONNECTION_ID, SIGNING_SECRET

    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _seed_connection(ideation_client._factory, product_id=pid)
    idea = _insert_idea(ideation_client._factory, pid)
    now = datetime.now(timezone.utc)
    assertion = jwt.encode(
        {
            "typ": "assertion", "aud": AUD, "iss": "sorento", "sub": "no-email",
            "connection_id": CONNECTION_ID, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
        },
        SIGNING_SECRET,
        algorithm=settings.jwt_algorithm,
    )
    minted = ideation_client.post(
        "/embed/session", json={"connection_id": CONNECTION_ID, "assertion": assertion}
    )
    assert minted.status_code == 200, minted.text
    b = _bearer(minted.json()["token"])
    res = _post(ideation_client, b, idea, "anon", prefix="/embed")
    assert res.status_code == 201, res.text
    assert res.json()["authorName"] == "Portal user"


def test_ac_19_10_embed_only_own_edit_delete_no_triage_override(emb):
    c, idea = emb["c"], emb["idea"]
    cid = _post(c, emb["bearer"], idea, "u1's", prefix="/embed").json()["id"]
    assert c.patch(_url(idea, cid, "/embed"), headers=emb["bearer2"], json={"body": "x"}).status_code == 403
    assert c.delete(_url(idea, cid, "/embed"), headers=emb["bearer2"]).status_code == 403
    seen = _listed(c, emb["bearer2"], idea, prefix="/embed")[0]
    assert (seen["isMine"], seen["canEdit"], seen["canDelete"]) == (False, False, False)


def test_ac_19_10_embed_422_validation(emb):
    assert _post(emb["c"], emb["bearer"], emb["idea"], "  ", prefix="/embed").status_code == 422


@pytest.mark.parametrize("which", ["other_product", "other_tenant"])
def test_ac_19_10_embed_cross_scope_404(emb, which):
    c, target, b = emb["c"], emb[which], emb["bearer"]
    assert c.get(_url(target, prefix="/embed"), headers=b).status_code == 404
    assert _post(c, b, target, prefix="/embed").status_code == 404
    assert c.patch(_url(target, "x", "/embed"), headers=b, json={"body": "x"}).status_code == 404
    assert c.delete(_url(target, "x", "/embed"), headers=b).status_code == 404


def test_ac_19_10_token_kinds_do_not_cross(emb):
    c, idea = emb["c"], emb["idea"]
    # operator JWT on the embed route
    assert c.get(_url(idea, prefix="/embed"), headers=emb["h"]).status_code == 401
    assert _post(c, emb["h"], idea, prefix="/embed").status_code == 401
    # embed token on the operator route
    assert c.get(_url(idea), headers=emb["bearer"]).status_code == 401
    assert _post(c, emb["bearer"], idea).status_code == 401
    # no token at all
    assert c.get(_url(idea, prefix="/embed")).status_code == 401


def test_ac_19_10_embed_comment_visible_to_operator(emb):
    _post(emb["c"], emb["bearer"], emb["idea"], "hello operator", prefix="/embed")
    rows = _listed(emb["c"], emb["h"], emb["idea"])
    assert rows[0]["authorKind"] == "embed" and rows[0]["isMine"] is False


# ── AC-19-11 ──────────────────────────────────────────────────────────────────
def _role_with(db, name, keys):
    from app.models import Role
    from app.models.permission import Permission

    role = Role(tenant_id=DEFAULT_TENANT_ID, name=name, description="t", is_system=False)
    role.permissions = db.query(Permission).filter(Permission.key.in_(list(keys))).all()
    db.add(role)
    db.commit()
    return role.id


def _held(db, role_id):
    from app.models import Role

    role = db.get(Role, role_id)
    db.refresh(role)
    return {p.key for p in role.permissions}


def test_ac_19_11_permission_row_in_csv():
    from pathlib import Path

    csv = (
        Path(__file__).resolve().parent.parent / "modules/ideation/permissions/permissions.csv"
    ).read_text()
    assert "ideation.ideas,Ideas,comment,Comment" in csv


def _drop_comment_permission(db):
    from app.models.permission import Permission

    perm = db.query(Permission).filter(Permission.key == COMMENT).first()
    if perm is not None:
        db.execute(text("DELETE FROM role_permissions WHERE permission_id = :p"), {"p": perm.id})
        db.execute(text("DELETE FROM permissions WHERE id = :p"), {"p": perm.id})
        db.commit()


def test_ac_19_11_install_sweeps_comment_to_upvote_holders_idempotent(ideation_session_factory):
    from modules.ideation.bootstrap import install

    db = ideation_session_factory()
    try:
        upvoter = _role_with(db, "Upvoter", [VIEW, UPVOTE])
        viewer = _role_with(db, "ViewerOnly", [VIEW])
        _drop_comment_permission(db)  # simulate: the sync creates it on this boot

        install(db.get_bind(), db)
        db.commit()
        assert COMMENT in _held(db, upvoter)
        assert COMMENT not in _held(db, viewer)  # never over-grants

        # A deliberate removal survives the next boot (one-shot).
        from app.models.permission import Permission

        pid = db.query(Permission).filter(Permission.key == COMMENT).one().id
        db.execute(
            text("DELETE FROM role_permissions WHERE role_id = :r AND permission_id = :p"),
            {"r": upvoter, "p": pid},
        )
        db.commit()
        install(db.get_bind(), db)
        db.commit()
        assert COMMENT not in _held(db, upvoter)
    finally:
        db.close()


def test_ac_19_11_sweep_scoped_per_tenant(ideation_session_factory):
    from app.models import Role
    from app.models.permission import Permission
    from modules.ideation.bootstrap import install
    from tests.ideation_build_helpers import ensure_other_tenant

    other = ensure_other_tenant(ideation_session_factory)
    db = ideation_session_factory()
    try:
        upvote = db.query(Permission).filter(Permission.key == UPVOTE).first()
        foreign = Role(tenant_id=other, name="ForeignUpvote", description="t", is_system=False)
        foreign.permissions = [upvote]
        db.add(foreign)
        db.commit()
        fid = foreign.id
        _drop_comment_permission(db)
        install(db.get_bind(), db)
        db.commit()
        perm = db.query(Permission).filter(Permission.key == COMMENT).one()
        rows = db.execute(
            text("SELECT tenant_id FROM role_permissions WHERE role_id = :r AND permission_id = :p"),
            {"r": fid, "p": perm.id},
        ).fetchall()
        assert len(rows) == 1 and rows[0][0] == other
    finally:
        db.close()

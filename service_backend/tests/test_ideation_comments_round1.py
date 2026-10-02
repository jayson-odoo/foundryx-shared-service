"""Plan 19 fix round 1 - RED tests (AC-19-29 amended, 32 amended, 36..38, 40 BE).

Written against the already-implemented lane: each test must fail against the
current code for the reason stated in its docstring.
"""
import pytest

from tests.test_ideation_comments import (  # noqa: F401
    COMMENT,
    MANAGE,
    VIEW,
    _listed,
    _post,
    _url,
    _user_h,
)
from tests.test_ideation_embed_writes import (  # noqa: F401
    _bearer,
    _mint,
    _seed_connection,
)
from tests.test_ideation_public_comments import _pub_post, _seed, _tok
from tests.test_ideation_public_comments import _url as _pub_url
from tests.test_ideation_public_status import (  # noqa: F401
    UNIFORM_404,
    ideation_client,
    setup,
)


# ── AC-19-29: public author = submitter FIRST name ────────────────────────────
@pytest.mark.parametrize("raw", ["+60 12-345 6789", "0123456789", "a@b.com", "Ali_0123"])
def test_ac_19_29_phone_or_email_shaped_submitter_becomes_submitter(setup, raw):
    """Fails today: authorName echoes the full submitter_name."""
    s = setup
    _seed(s, _tok("1"), submitter_name=raw)
    res = _pub_post(s["client"], _tok("1"), "hello")
    assert res.status_code == 201, res.text
    assert res.json()["authorName"] == "Submitter"
    assert raw not in str(res.json())


def test_ac_19_29_single_token_name_passes_through(setup):
    s = setup
    _seed(s, _tok("2"), submitter_name="Madonna")
    assert _pub_post(s["client"], _tok("2"), "hi").json()["authorName"] == "Madonna"


def test_ac_19_29_list_shows_first_name_not_full(setup):
    s = setup
    _seed(s, _tok("3"), submitter_name="Alice Tan")
    _pub_post(s["client"], _tok("3"), "hi")
    rows = s["client"].get(_pub_url(_tok("3"))).json()
    assert rows[0]["authorName"] == "Alice"
    assert "Tan" not in str(rows)


# ── AC-19-32: public projection of staff / embed names ────────────────────────
def test_ac_19_32_public_list_never_contains_an_email(setup):
    """Fails today: the stored email-as-name (embed email claim, nameless staff)
    reaches the public JSON."""
    s = setup
    c = s["client"]
    iid = _seed(s, _tok("4"))
    from app.models import User

    # embed commenter with an email claim (a@sorento.my)
    _seed_connection(s["factory"], product_id=s["product_id"])
    emb = _bearer(_mint(c, sub="user-9"))
    # the embed scope needs the idea in the connection's product: _seed uses s["product_id"]
    made = c.post(f"/embed/ideas/{iid}/comments", headers=emb, json={"body": "from portal"})
    assert made.status_code == 201, made.text
    # nameless staff user -> stored author_name is the email
    staff = _user_h(c, "nameless@example.com", {VIEW, COMMENT})
    db = s["factory"]()
    try:
        u = db.query(User).filter(User.email == "nameless@example.com").one()
        u.name = None
        db.commit()
    finally:
        db.close()
    assert _post(c, staff, iid, "staff no name").status_code == 201
    # a normal staff name
    named = _user_h(c, "named@example.com", {VIEW, COMMENT})
    assert _post(c, named, iid, "staff named").status_code == 201

    res = c.get(_pub_url(_tok("4")))
    assert res.status_code == 200, res.text
    assert "@" not in res.text
    by_body = {r["body"]: r for r in res.json()}
    assert by_body["from portal"]["authorName"] == "Portal user"
    assert by_body["staff no name"]["authorName"] == "Team member"
    assert by_body["staff named"]["authorName"] == "Test User"  # normal name passes through

    # Operator + embed lists keep the stored name.
    op = {r["body"]: r for r in _listed(c, s["h"], iid)}
    assert op["from portal"]["authorName"] == "a@sorento.my"
    assert op["staff no name"]["authorName"] == "nameless@example.com"
    em = {r["body"]: r for r in _listed(c, emb, iid, prefix="/embed")}
    # AC-19-45 (round 2): the EMBED list also projects email-shaped names.
    assert em["from portal"]["authorName"] == "Portal user"
    assert em["staff no name"]["authorName"] == "Team member"
    assert em["staff named"]["authorName"] == "Test User"


# ── AC-19-36: control characters ──────────────────────────────────────────────
BAD_BODIES = ["a\u0000b", "a\u0007b"]


@pytest.mark.parametrize("bad", BAD_BODIES)
def test_ac_19_36_operator_rejects_control_chars(setup, bad):
    """Fails today: NUL / BEL accepted (201)."""
    s = setup
    iid = _seed(s, _tok("5"))
    c = s["client"]
    assert _post(c, s["h"], iid, bad).status_code == 422
    ok = _post(c, s["h"], iid, "fine")
    assert ok.status_code == 201
    r = c.patch(_url(iid, ok.json()["id"]), headers=s["h"], json={"body": bad})
    assert r.status_code == 422


@pytest.mark.parametrize("bad", BAD_BODIES)
def test_ac_19_36_embed_rejects_control_chars(setup, bad):
    s = setup
    iid = _seed(s, _tok("6"))
    _seed_connection(s["factory"], product_id=s["product_id"])
    emb = _bearer(_mint(s["client"]))
    res = s["client"].post(f"/embed/ideas/{iid}/comments", headers=emb, json={"body": bad})
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("bad", BAD_BODIES)
def test_ac_19_36_public_rejects_control_chars_without_burning_budget(setup, bad):
    s = setup
    _seed(s, _tok("7"))
    for _ in range(6):
        assert _pub_post(s["client"], _tok("7"), bad).status_code == 422
    for i in range(5):  # the 5/15min budget is intact
        assert _pub_post(s["client"], _tok("7"), f"ok{i}").status_code == 201


def test_ac_19_36_newline_and_tab_allowed(setup):
    s = setup
    iid = _seed(s, _tok("8"))
    assert _post(s["client"], s["h"], iid, "line1\nline2\tcol").status_code == 201
    assert _pub_post(s["client"], _tok("8"), "line1\nline2\tcol").status_code == 201


# ── AC-19-37: DELETE needs view first (no existence oracle) ───────────────────
def test_ac_19_37_delete_without_view_is_403_for_known_and_unknown_id(setup):
    """Fails today: unknown id -> 404 vs known -> 403 (an oracle)."""
    s = setup
    c = s["client"]
    iid = _seed(s, _tok("9"))
    cid = _post(c, s["h"], iid, "exists").json()["id"]
    blind = _user_h(c, "noview@example.com", {COMMENT})
    assert c.delete(_url(iid, cid), headers=blind).status_code == 403
    assert c.delete(_url(iid, "no-such-comment"), headers=blind).status_code == 403
    assert len(_listed(c, s["h"], iid)) == 1


# ── AC-19-38: module not active -> uniform 404 on public surfaces ─────────────
def test_ac_19_38_inactive_ideation_module_is_uniform_404(setup):
    """Fails today: the public routes ignore the tenant's module status."""
    from app.models import DEFAULT_TENANT_ID
    from app.models.module import Module, TenantModule

    s = setup
    c = s["client"]
    _seed(s, _tok("a"))
    assert c.get(f"/public/ideas/{_tok('a')}").status_code == 200  # control: served while active
    db = s["factory"]()
    try:
        module = db.query(Module).filter(Module.name == "ideation").one()
        row = (
            db.query(TenantModule)
            .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID, TenantModule.module_id == module.id)
            .one()
        )
        row.status = "DISABLED"
        db.commit()
    finally:
        db.close()
    for res in (
        c.get(f"/public/ideas/{_tok('a')}"),
        c.get(_pub_url(_tok("a"))),
        _pub_post(c, _tok("a"), "hi"),
    ):
        assert res.status_code == 404, res.text
        assert res.json() == UNIFORM_404


# ── AC-19-40 (BE): replying into a thread whose top-level is deleted ──────────
def test_ac_19_40_reply_to_live_reply_of_deleted_top_level_attaches_to_top_level(setup):
    """Fails today: parent resolution rejects the deleted top-level (404)."""
    from modules.ideation.models import IdeaComment

    s = setup
    c = s["client"]
    iid = _seed(s, _tok("b"))
    top = _post(c, s["h"], iid, "top").json()["id"]
    reply = _post(c, s["h"], iid, "reply", parent_id=top).json()["id"]
    assert c.delete(_url(iid, top), headers=s["h"]).status_code == 204
    res = _post(c, s["h"], iid, "answer", parent_id=reply)
    assert res.status_code == 201, res.text
    assert res.json()["parentId"] == top
    db = s["factory"]()
    try:
        assert db.get(IdeaComment, res.json()["id"]).parent_id == top
    finally:
        db.close()
    # the public route behaves the same
    assert _pub_post(c, _tok("b"), "pub answer", parent_id=reply).status_code == 201


def test_ac_19_40_deleted_top_level_without_live_replies_is_not_a_parent(setup):
    s = setup
    c = s["client"]
    iid = _seed(s, _tok("c"))
    top = _post(c, s["h"], iid, "top").json()["id"]
    assert c.delete(_url(iid, top), headers=s["h"]).status_code == 204
    assert _post(c, s["h"], iid, "orphan", parent_id=top).status_code == 404

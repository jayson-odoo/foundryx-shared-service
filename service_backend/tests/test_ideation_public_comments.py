"""Plan 19 section F - public status page comments (AC-19-28..32), RED tests.

``GET|POST /public/ideas/{token}/comments``: the ``status_token`` is the
capability (no auth). Uniform 404 envelope, no-store/noindex/no-referrer,
author name from the idea's submitter (never the client), 2000-char cap,
per-token (5) and per-IP (20) throttle with Retry-After, no public edit/delete.
"""
import pytest

from tests.test_ideation_comments import _post as _op_post  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    UNIFORM_404,
    _make_captured_idea,
    ideation_client,
    setup,
)


def _tok(c: str) -> str:
    return "tokc_" + c * 19


def _url(token, comment_id=None):
    base = f"/public/ideas/{token}/comments"
    return f"{base}/{comment_id}" if comment_id else base


def _pub_post(client, token, body="hi", parent_id=None, **extra):
    payload = {"body": body, **extra}
    if parent_id is not None:
        payload["parentId"] = parent_id
    return client.post(_url(token), json=payload)


def _seed(s, token, **kw):
    kw.setdefault("idea_number", "IDEA-1901")
    return _make_captured_idea(s["factory"], s["product_id"], status_token=token, **kw)


# ── AC-19-28 read ─────────────────────────────────────────────────────────────
def test_ac_19_28_empty_list_and_headers(setup):
    s = setup
    _seed(s, _tok("a"))
    res = s["client"].get(_url(_tok("a")))
    assert res.status_code == 200, res.text
    assert res.json() == []
    assert res.headers.get("cache-control") == "no-store"
    assert res.headers.get("x-robots-tag") == "noindex"
    assert res.headers.get("referrer-policy") == "no-referrer"


@pytest.mark.parametrize(
    "token",
    ["unknown-token-that-does-not-exist", "bad token!", "x" * 15, "x" * 400, "IDEA-0001"],
)
def test_ac_19_28_malformed_or_unknown_token_uniform_404(setup, token):
    g = setup["client"].get(_url(token))
    p = _pub_post(setup["client"], token)
    for res in (g, p):
        assert res.status_code == 404
        assert res.json() == UNIFORM_404


def test_ac_19_28_draft_status_row_404(setup):
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import initial_idea_status_id
    from app.models import DEFAULT_TENANT_ID

    s = setup
    token = _tok("d")
    db = s["factory"]()
    try:
        db.add(
            Idea(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=s["product_id"],
                status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
                problem="draft",
                status_token=token,
            )
        )
        db.commit()
    finally:
        db.close()
    res = s["client"].get(_url(token))
    assert res.status_code == 404 and res.json() == UNIFORM_404
    assert _pub_post(s["client"], token).status_code == 404


def test_ac_19_28_blocked_tenant_404(setup):
    from app.models.status import TENANT_STATUS_IDS, TENANT_STATUS_SUSPENDED
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    s = setup
    token = _tok("z")
    db = s["factory"]()
    try:
        t = Tenant(
            name="Suspended Co", slug="suspended-comments",
            status_id=TENANT_STATUS_IDS[TENANT_STATUS_SUSPENDED],
        )
        db.add(t)
        db.flush()
        db.add(
            Idea(
                tenant_id=t.id, product_id=s["product_id"],
                status_id=idea_status_id(db, "captured", t.id),
                problem="x", idea_number="IDEA-9002", status_token=token,
                captured_json={"problem": "x"},
            )
        )
        db.commit()
    finally:
        db.close()
    res = s["client"].get(_url(token))
    assert res.status_code == 404 and res.json() == UNIFORM_404
    assert _pub_post(s["client"], token).status_code == 404


def test_ac_19_28_list_flags_always_false_and_no_author_id(setup):
    s = setup
    _seed(s, _tok("b"))
    assert _pub_post(s["client"], _tok("b"), "mine").status_code == 201
    rows = s["client"].get(_url(_tok("b"))).json()
    r = rows[0]
    assert set(r) >= {
        "id", "ideaId", "parentId", "authorName", "authorKind", "body",
        "isDeleted", "isMine", "canEdit", "canDelete", "createdAt", "editedAt",
    }
    assert (r["isMine"], r["canEdit"], r["canDelete"]) == (False, False, False)
    assert r["authorKind"] == "public"
    assert "authorId" not in r and "author_id" not in r


def test_ac_19_28_merged_child_returns_own_thread_only_and_post_409(setup):
    from modules.ideation.models import Idea

    s = setup
    h = s["h"]
    survivor = _seed(s, _tok("s"), idea_number="IDEA-1902")
    child = _seed(s, _tok("c"), idea_number="IDEA-1903")
    _pub_post(s["client"], _tok("c"), "child's own")
    _pub_post(s["client"], _tok("s"), "survivor's thread")
    db = s["factory"]()
    try:
        db.get(Idea, child).merged_into_id = survivor
        db.commit()
    finally:
        db.close()
    rows = s["client"].get(_url(_tok("c"))).json()
    assert [r["body"] for r in rows] == ["child's own"]  # never the survivor's thread
    assert _pub_post(s["client"], _tok("c"), "nope").status_code == 409


# ── AC-19-29 post ─────────────────────────────────────────────────────────────
def test_ac_19_29_post_201_author_from_submitter_ignores_client_name(setup):
    from modules.ideation.models import IdeaComment

    s = setup
    iid = _seed(s, _tok("e"), submitter_name="Alice Tan")
    res = _pub_post(
        s["client"], _tok("e"), "  from visitor ", authorName="Evil", author_name="Evil",
        authorKind="user", authorId="admin",
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["body"] == "from visitor"
    assert body["authorName"] == "Alice Tan"
    assert body["authorKind"] == "public"
    db = s["factory"]()
    try:
        row = db.get(IdeaComment, body["id"])
        assert row.author_kind == "public"
        assert row.author_id == f"public:{iid}"
    finally:
        db.close()


def test_ac_19_29_author_name_falls_back_to_submitter_literal(setup):
    s = setup
    _seed(s, _tok("f"), submitter_name=None)
    res = _pub_post(s["client"], _tok("f"), "anon")
    assert res.status_code == 201, res.text
    assert res.json()["authorName"] == "Submitter"


@pytest.mark.parametrize("bad", ["", "  \n", "x" * 2001])
def test_ac_19_29_body_validation_422(setup, bad):
    _seed(setup, _tok("g"))
    assert _pub_post(setup["client"], _tok("g"), bad).status_code == 422


def test_ac_19_29_body_2000_ok(setup):
    _seed(setup, _tok("h"))
    assert _pub_post(setup["client"], _tok("h"), "x" * 2000).status_code == 201


def test_ac_19_29_cross_idea_parent_404(setup):
    s = setup
    _seed(s, _tok("i"), idea_number="IDEA-1904")
    _seed(s, _tok("j"), idea_number="IDEA-1905")
    other_parent = _pub_post(s["client"], _tok("j"), "on j").json()["id"]
    res = _pub_post(s["client"], _tok("i"), "cross", parent_id=other_parent)
    assert res.status_code == 404, res.text
    assert s["client"].get(_url(_tok("i"))).json() == []


def test_ac_19_29_reply_to_reply_normalised(setup):
    s = setup
    _seed(s, _tok("k"))
    top = _pub_post(s["client"], _tok("k"), "top").json()["id"]
    rep = _pub_post(s["client"], _tok("k"), "reply", parent_id=top)
    assert rep.status_code == 201 and rep.json()["parentId"] == top
    nested = _pub_post(s["client"], _tok("k"), "nested", parent_id=rep.json()["id"])
    assert nested.status_code == 201, nested.text
    assert nested.json()["parentId"] == top


def test_ac_19_29_no_auth_header_needed_and_oldest_first(setup):
    s = setup
    _seed(s, _tok("l"))
    _pub_post(s["client"], _tok("l"), "one")
    _pub_post(s["client"], _tok("l"), "two")
    assert [r["body"] for r in s["client"].get(_url(_tok("l"))).json()] == ["one", "two"]


# ── AC-19-30 throttle ─────────────────────────────────────────────────────────
def test_ac_19_30_sixth_post_on_one_token_is_429_with_retry_after(setup):
    s = setup
    _seed(s, _tok("m"))
    for i in range(5):
        assert _pub_post(s["client"], _tok("m"), f"c{i}").status_code == 201
    res = _pub_post(s["client"], _tok("m"), "one too many")
    assert res.status_code == 429, res.text
    assert int(res.headers["retry-after"]) > 0
    # reads are not throttled
    assert s["client"].get(_url(_tok("m"))).status_code == 200
    assert len(s["client"].get(_url(_tok("m"))).json()) == 5


def test_ac_19_30_per_ip_cap_across_different_tokens(setup):
    s = setup
    tokens = [_tok(c) for c in "nopqr"]
    for i, t in enumerate(tokens):
        _seed(s, t, idea_number=f"IDEA-19{20 + i}")
    sent = 0
    for t in tokens[:4]:  # 4 tokens x 5 = 20 posts, none over the per-token cap
        for i in range(5):
            assert _pub_post(s["client"], t, f"c{i}").status_code == 201
            sent += 1
    assert sent == 20
    res = _pub_post(s["client"], tokens[4], "21st from the same IP")
    assert res.status_code == 429, res.text
    assert int(res.headers["retry-after"]) > 0


def test_ac_19_30_failed_validation_does_not_burn_the_budget(setup):
    s = setup
    _seed(s, _tok("t"))
    for _ in range(6):
        assert _pub_post(s["client"], _tok("t"), "").status_code == 422
    assert _pub_post(s["client"], _tok("t"), "still allowed").status_code == 201


# ── AC-19-31 ──────────────────────────────────────────────────────────────────
def test_ac_19_31_no_public_edit_or_delete_routes(setup):
    s = setup
    _seed(s, _tok("u"))
    cid = _pub_post(s["client"], _tok("u"), "mine").json()["id"]
    assert s["client"].patch(_url(_tok("u"), cid), json={"body": "x"}).status_code in (404, 405)
    assert s["client"].delete(_url(_tok("u"), cid)).status_code in (404, 405)
    assert s["client"].get(_url(_tok("u"))).json()[0]["body"] == "mine"


def test_ac_19_31_triage_manager_deletes_public_comment(setup):
    s = setup
    iid = _seed(s, _tok("v"))
    cid = _pub_post(s["client"], _tok("v"), "visitor says").json()["id"]
    listed = s["client"].get(f"/ideation/ideas/{iid}/comments", headers=s["h"])
    assert listed.status_code == 200, listed.text
    row = listed.json()[0]
    assert row["authorKind"] == "public" and row["canDelete"] is True
    assert row["canEdit"] is False and row["isMine"] is False
    assert "authorId" not in row
    res = s["client"].delete(f"/ideation/ideas/{iid}/comments/{cid}", headers=s["h"])
    assert res.status_code == 204, res.text
    assert s["client"].get(_url(_tok("v"))).json() == []


# ── AC-19-32 ──────────────────────────────────────────────────────────────────
def test_ac_19_32_staff_comment_shows_real_name_on_public_list(setup):
    s = setup
    iid = _seed(s, _tok("w"))
    res = s["client"].post(
        f"/ideation/ideas/{iid}/comments", headers=s["h"], json={"body": "staff reply"}
    )
    assert res.status_code == 201, res.text
    staff_name = res.json()["authorName"]
    rows = s["client"].get(_url(_tok("w"))).json()
    assert rows[0]["body"] == "staff reply"
    assert rows[0]["authorName"] == staff_name
    assert rows[0]["authorKind"] == "user"
    assert (rows[0]["isMine"], rows[0]["canEdit"], rows[0]["canDelete"]) == (False, False, False)
    assert "authorId" not in rows[0]


def test_ac_19_32_public_list_only_that_ideas_comments_and_tenant(setup):
    s = setup
    _seed(s, _tok("x"), idea_number="IDEA-1930")
    other = _seed(s, _tok("y"), idea_number="IDEA-1931")
    made = s["client"].post(
        f"/ideation/ideas/{other}/comments", headers=s["h"], json={"body": "on the other idea"}
    )
    assert made.status_code == 201, made.text
    foreign = _seed(s, _tok("w"), idea_number="IDEA-1932", tenant_id="tenant-x")
    assert foreign
    res = s["client"].get(_url(_tok("x")))
    assert res.status_code == 200 and res.json() == []


def test_ac_19_32_author_id_not_on_embed_or_operator_wire(setup):
    s = setup
    iid = _seed(s, _tok("q"))
    made = s["client"].post(f"/ideation/ideas/{iid}/comments", headers=s["h"], json={"body": "x"})
    assert made.status_code == 201, made.text
    listed = s["client"].get(f"/ideation/ideas/{iid}/comments", headers=s["h"])
    assert listed.status_code == 200 and len(listed.json()) == 1
    for r in listed.json():
        assert "authorId" not in r

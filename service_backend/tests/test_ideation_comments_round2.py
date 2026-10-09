"""Plan 19 fix round 2 - RED tests (AC-19-44 lone surrogates, AC-19-45 embed name projection)."""
import pytest

from tests.test_ideation_comments import COMMENT, VIEW, _listed, _post, _url, _user_h
from tests.test_ideation_comments_round1 import (  # noqa: F401
    _bearer,
    _mint,
    _pub_post,
    _pub_url,
    _seed,
    _seed_connection,
    _tok,
    ideation_client,
    setup,
)

JSON = {"content-type": "application/json"}
# Raw JSON text carrying the surrogate ESCAPE (httpx json= may refuse to encode it).
SURROGATE_BODIES = ['{"body": "a\\ud800b"}', '{"body": "a\\udc00b"}']


def _raw(client, method, url, raw, headers=None):
    return client.request(method, url, content=raw, headers={**(headers or {}), **JSON})


@pytest.mark.parametrize("raw", SURROGATE_BODIES)
def test_ac_19_44_operator_post_and_patch_reject_lone_surrogates(setup, raw):
    """Must be 422 (never 500, never stored)."""
    s = setup
    c = s["client"]
    iid = _seed(s, _tok("d"))
    res = _raw(c, "POST", _url(iid), raw, s["h"])
    assert res.status_code == 422, res.text
    ok = _post(c, s["h"], iid, "fine")
    assert ok.status_code == 201
    res = _raw(c, "PATCH", _url(iid, ok.json()["id"]), raw, s["h"])
    assert res.status_code == 422, res.text
    assert [r["body"] for r in _listed(c, s["h"], iid)] == ["fine"]


@pytest.mark.parametrize("raw", SURROGATE_BODIES)
def test_ac_19_44_embed_post_rejects_lone_surrogates(setup, raw):
    s = setup
    iid = _seed(s, _tok("e"))
    _seed_connection(s["factory"], product_id=s["product_id"])
    emb = _bearer(_mint(s["client"]))
    res = _raw(s["client"], "POST", f"/embed/ideas/{iid}/comments", raw, emb)
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("raw", SURROGATE_BODIES)
def test_ac_19_44_public_post_rejects_lone_surrogates_without_burning_budget(setup, raw):
    s = setup
    _seed(s, _tok("f"))
    for _ in range(6):
        assert _raw(s["client"], "POST", _pub_url(_tok("f")), raw).status_code == 422
    for i in range(5):  # budget intact
        assert _pub_post(s["client"], _tok("f"), f"ok{i}").status_code == 201


def test_ac_19_45_embed_list_projects_email_shaped_names(setup):
    """Fails today: the embed list echoes the stored email-shaped author names."""
    from app.models import User

    s = setup
    c = s["client"]
    iid = _seed(s, _tok("g"))
    _seed_connection(s["factory"], product_id=s["product_id"])
    emb = _bearer(_mint(c, sub="user-7"))
    other = _bearer(_mint(c, sub="user-8"))
    assert c.post(f"/embed/ideas/{iid}/comments", headers=emb, json={"body": "from portal"}).status_code == 201
    staff = _user_h(c, "nameless2@example.com", {VIEW, COMMENT})
    db = s["factory"]()
    try:
        u = db.query(User).filter(User.email == "nameless2@example.com").one()
        u.name = None
        db.commit()
    finally:
        db.close()
    assert _post(c, staff, iid, "staff no name").status_code == 201
    named = _user_h(c, "named2@example.com", {VIEW, COMMENT})
    assert _post(c, named, iid, "staff named").status_code == 201

    em = {r["body"]: r for r in _listed(c, emb, iid, prefix="/embed")}
    assert em["from portal"]["authorName"] == "Portal user"
    assert em["staff no name"]["authorName"] == "Team member"
    assert em["staff named"]["authorName"] == "Test User"
    assert "@" not in str(list(em.values()))
    # flags unchanged for the portal author, and for another portal user
    mine = em["from portal"]
    assert (mine["isMine"], mine["canEdit"], mine["canDelete"]) == (True, True, True)
    theirs = {r["body"]: r for r in _listed(c, other, iid, prefix="/embed")}["from portal"]
    assert (theirs["isMine"], theirs["canEdit"], theirs["canDelete"]) == (False, False, False)
    # operator list keeps the stored names
    op = {r["body"]: r for r in _listed(c, s["h"], iid)}
    assert op["from portal"]["authorName"] == "a@sorento.my"
    assert op["staff no name"]["authorName"] == "nameless2@example.com"

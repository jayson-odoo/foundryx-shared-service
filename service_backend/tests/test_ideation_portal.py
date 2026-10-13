"""IDEA-PORTAL - signed-in Canny-style idea portal (lane IDEA-PORTAL), RED first.

Contract: ``documentation/plans/sprint-5/idea-portal/acceptance-criteria.md``
(AC-P-xx ids below). Every ``/portal/ideas/*`` route needs a PORTAL token,
minted by one of two exchanges: staff (core login) or crm (Sorento CRM user
through the ideation embed SSO). Dealers cannot sign in (owner Q1, 13 Oct).
"""
from datetime import datetime, timedelta, timezone

from jose import jwt
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_embed import (  # noqa: F401
    _assertion,
    _seed_connection,
)
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    _make_captured_idea,
    ideation_client,
    setup,
)

UNAUTH = {"error": {"code": "unauthorized", "message": "Sign in to continue."}}


# ── helpers ───────────────────────────────────────────────────────────────────


def _staff_session(s) -> dict:
    res = s["client"].post("/portal/ideas/session/staff", headers=s["h"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["principal"]["kind"] == "staff"
    return {"Authorization": f"Bearer {body['token']}"}


def _crm_session(s, *, sub="crm-user-1", name="Alice Tan", product_id=None, ideas_manage=None) -> dict:
    from modules.ideation.services.embed import upsert_connection

    db = s["factory"]()
    try:
        upsert_connection(
            db,
            connection_id="sorento-portal",
            tenant_id=DEFAULT_TENANT_ID,
            signing_secret="portal-secret-value-123",
            allowed_origins=["https://fe-sorento.foundryx.my"],
            is_active=True,
            product_id=product_id,
        )
    finally:
        db.close()
    a = _assertion(
        secret="portal-secret-value-123", connection_id="sorento-portal", sub=sub, name=name
    )
    if ideas_manage is not None:
        claims = jwt.get_unverified_claims(a)
        claims["ideas_manage"] = ideas_manage
        a = jwt.encode(claims, "portal-secret-value-123", algorithm=settings.jwt_algorithm)
    emb = s["client"].post("/embed/session", json={"connection_id": "sorento-portal", "assertion": a})
    assert emb.status_code == 200, emb.text
    embed_token = emb.json()["token"]
    res = s["client"].post("/portal/ideas/session/embed", json={"token": embed_token})
    assert res.status_code == 200, res.text
    assert res.json()["principal"]["kind"] == "crm"
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _idea(s, n, *, status_key="captured", token=None, crm_user=None, **kw):
    from modules.ideation.models import Idea

    iid = _make_captured_idea(
        s["factory"],
        s["product_id"],
        idea_number=f"IDEA-{n:04d}",
        status_token=token,
        status_key=status_key,
        **kw,
    )
    if crm_user:
        db = s["factory"]()
        try:
            db.query(Idea).filter(Idea.id == iid).first().submitter_crm_user_id = crm_user
            db.commit()
        finally:
            db.close()
    return iid


# ── A. sign-in ────────────────────────────────────────────────────────────────


def test_ac_p_01_staff_session_principal(setup):
    h = _staff_session(setup)
    me = setup["client"].get("/portal/ideas/me", headers=h)
    assert me.status_code == 200, me.text
    assert me.json()["kind"] == "staff"
    assert me.json()["role"] == "Staff"
    assert me.json()["name"]


def test_ac_p_01_staff_session_needs_login(setup):
    res = setup["client"].post("/portal/ideas/session/staff")
    assert res.status_code == 401


def test_ac_p_02_crm_session(setup):
    h = _crm_session(setup)
    me = setup["client"].get("/portal/ideas/me", headers=h).json()
    assert me["kind"] == "crm" and me["name"] == "Alice" and me["role"] == "Staff"
    assert me["canManage"] is True  # no ideas_manage claim = unrestricted (embed rule)
    restricted = _crm_session(setup, sub="crm-user-2", ideas_manage=False)
    assert setup["client"].get("/portal/ideas/me", headers=restricted).json()["canManage"] is False


def test_ac_p_02_bad_embed_token(setup):
    res = setup["client"].post("/portal/ideas/session/embed", json={"token": "nope"})
    assert res.status_code == 401


def test_ac_p_03_no_dealer_sign_in(setup):
    """Owner Q1 (13 Oct): dealers / WhatsApp contacts cannot sign in at all."""
    res = setup["client"].post("/portal/ideas/session/link", json={"token": "x" * 20, "last4": "6789"})
    assert res.status_code in (401, 404, 405)
    assert "token" not in res.text


def test_ac_p_04_routes_need_portal_token(setup):
    s = setup
    for path in ("/portal/ideas/me", "/portal/ideas/roadmap", "/portal/ideas", "/portal/ideas/changelog"):
        assert s["client"].get(path).status_code == 401
        # A core JWT is not a portal token.
        assert s["client"].get(path, headers=s["h"]).status_code == 401


def test_ac_p_04_expired_or_foreign_token(setup):
    s = setup
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"typ": "idea_portal", "tenant_id": DEFAULT_TENANT_ID, "kind": "staff", "sub": "x",
         "exp": int((now - timedelta(minutes=1)).timestamp())},
        settings.jwt_secret, algorithm="HS256",
    )
    forged = jwt.encode(
        {"typ": "idea_portal", "tenant_id": DEFAULT_TENANT_ID, "kind": "staff", "sub": "x",
         "exp": int((now + timedelta(hours=1)).timestamp())},
        "not-the-secret", algorithm="HS256",
    )
    for t in (expired, forged):
        assert s["client"].get("/portal/ideas/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_ac_p_04_module_inactive_rejects_token(setup):
    from app.models.module import Module, TenantModule

    s = setup
    h = _staff_session(s)
    db = s["factory"]()
    try:
        tm = (
            db.query(TenantModule)
            .join(Module, Module.id == TenantModule.module_id)
            .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID, Module.name == "ideation")
            .first()
        )
        tm.status = "INACTIVE"
        db.commit()
    finally:
        db.close()
    assert s["client"].get("/portal/ideas/me", headers=h).status_code == 401


# ── B. visibility ─────────────────────────────────────────────────────────────


def test_ac_p_10_hidden_rows_never_listed(setup):
    from modules.ideation.models import Idea

    s = setup
    visible = _idea(s, 101, title="Order status tracking for dealers")
    _idea(s, 102, status_key="draft", title="draft one")
    _idea(s, 103, is_test=True, title="test one")
    child = _idea(s, 104, title="merged child")
    db = s["factory"]()
    try:
        row = db.query(Idea).filter(Idea.id == child).first()
        row.merged_into_id = visible
        db.commit()
    finally:
        db.close()
    h = _staff_session(s)
    ids = [i["id"] for i in s["client"].get("/portal/ideas", headers=h).json()["items"]]
    assert ids == [visible]
    # A merged child's page resolves to the survivor.
    page = s["client"].get(f"/portal/ideas/{child}", headers=h)
    assert page.status_code == 200 and page.json()["id"] == visible
    # Draft / test ids are 404.
    db = s["factory"]()
    try:
        draft_id = db.query(Idea.id).filter(Idea.idea_number == "IDEA-0102").scalar()
        test_id = db.query(Idea.id).filter(Idea.idea_number == "IDEA-0103").scalar()
    finally:
        db.close()
    for i in (draft_id, test_id, "no-such-id"):
        assert s["client"].get(f"/portal/ideas/{i}", headers=h).status_code == 404


def test_ac_p_10_other_tenant_never_visible(setup):
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    s = setup
    db = s["factory"]()
    try:
        t = Tenant(name="Other Co", slug="other-portal", status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE])
        db.add(t)
        db.flush()
        foreign = Idea(
            tenant_id=t.id, product_id=s["product_id"],
            status_id=idea_status_id(db, "captured", t.id),
            problem="foreign", idea_number="IDEA-0901",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    finally:
        db.close()
    h = _staff_session(s)
    assert s["client"].get("/portal/ideas", headers=h).json()["items"] == []
    assert s["client"].get(f"/portal/ideas/{foreign_id}", headers=h).status_code == 404
    assert s["client"].post(f"/portal/ideas/{foreign_id}/vote", headers=h).status_code == 404


def test_ac_p_11_portal_hidden_only_managers_and_submitter(setup):
    from modules.ideation.models import Idea

    s = setup
    hc = _crm_session(s, sub="crm-sales-1", ideas_manage=False)
    own_idea = _idea(s, 60, crm_user="crm-sales-1")
    other = _idea(s, 61, title="internal pricing idea")
    db = s["factory"]()
    try:
        for i in (own_idea, other):
            db.query(Idea).filter(Idea.id == i).first().portal_hidden = True
        db.commit()
    finally:
        db.close()
    seen = {i["id"] for i in s["client"].get("/portal/ideas", headers=hc).json()["items"]}
    assert own_idea in seen and other not in seen
    assert s["client"].get(f"/portal/ideas/{other}", headers=hc).status_code == 404
    staff = {i["id"] for i in s["client"].get("/portal/ideas", headers=_staff_session(s)).json()["items"]}
    assert {own_idea, other} <= staff


def test_ac_p_11_hide_toggle_managers_only(setup):
    s = setup
    iid = _idea(s, 62)
    c = s["client"]
    restricted = _crm_session(s, sub="crm-sales-2", ideas_manage=False)
    assert c.put(f"/portal/ideas/{iid}/hidden", headers=restricted, json={"hidden": True}).status_code == 403
    assert c.get(f"/portal/ideas/{iid}", headers=restricted).json()["portalHidden"] is None
    hs = _staff_session(s)
    res = c.put(f"/portal/ideas/{iid}/hidden", headers=hs, json={"hidden": True})
    assert res.status_code == 200 and res.json()["portalHidden"] is True
    assert c.get(f"/portal/ideas/{iid}", headers=restricted).status_code == 404


def test_ac_p_10_crm_product_scope(setup):
    s = setup
    from tests.test_ideation_public_status import _create_software_product

    other_product = _create_software_product(s["client"], s["h"], name="Other App")
    mine = _idea(s, 70)
    _make_captured_idea(s["factory"], other_product, idea_number="IDEA-0071")
    h = _crm_session(s, product_id=s["product_id"])
    ids = [i["id"] for i in s["client"].get("/portal/ideas", headers=h).json()["items"]]
    assert ids == [mine]


# ── C. roadmap ────────────────────────────────────────────────────────────────


def test_ac_p_20_roadmap_columns_mapping(setup):
    s = setup
    ids = {
        k: _idea(s, n, status_key=k, title=f"t {k}")
        for n, k in enumerate(
            ["captured", "triaged", "linked", "building", "delivered", "closed",
             "rejected", "duplicate", "archived"], start=200,
        )
    }
    h = _staff_session(s)
    res = s["client"].get("/portal/ideas/roadmap", headers=h)
    assert res.status_code == 200, res.text
    cols = res.json()["columns"]
    assert [c["key"] for c in cols] == ["under_review", "planned", "in_progress", "complete"]
    assert [c["title"] for c in cols] == ["Under review", "Planned", "In progress", "Complete"]
    by = {c["key"]: {i["id"] for i in c["ideas"]} for c in cols}
    assert by["under_review"] == {ids["captured"], ids["triaged"]}
    assert by["planned"] == {ids["linked"]}
    assert by["in_progress"] == {ids["building"]}
    assert by["complete"] == {ids["delivered"], ids["closed"]}


def test_ac_p_21_unmapped_status_gets_own_column(setup):
    from app.models.status import Status
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import IDEA_ENTITY

    s = setup
    iid = _idea(s, 300)
    db = s["factory"]()
    try:
        st = Status(
            entity_type=IDEA_ENTITY, tenant_id=None, key="qa", category="QA",
            label="In QA", color="teal", sort_order=5,
        )
        db.add(st)
        db.flush()
        db.query(Idea).filter(Idea.id == iid).first().status_id = st.id
        db.commit()
    finally:
        db.close()
    cols = s["client"].get("/portal/ideas/roadmap", headers=_staff_session(s)).json()["columns"]
    qa = [c for c in cols if c["title"] == "In QA"]
    assert qa and [i["id"] for i in qa[0]["ideas"]] == [iid]


def test_ac_p_22_cards_sorted_by_votes_and_mine(setup):
    s = setup
    hc = _crm_session(s, sub="crm-sales-3")
    own = _idea(s, 80, crm_user="crm-sales-3")
    a = _idea(s, 81, upvotes=5)
    b = _idea(s, 82, upvotes=9)
    cols = s["client"].get("/portal/ideas/roadmap", headers=hc).json()["columns"]
    review = cols[0]["ideas"]
    assert [i["id"] for i in review] == [b, a, own]
    card = review[2]
    assert set(card) >= {"id", "ideaNumber", "title", "upvotes", "commentCount", "isMine", "myVote"}
    assert card["isMine"] is True and review[0]["isMine"] is False
    mine = s["client"].get("/portal/ideas/roadmap?mine=true", headers=hc).json()["columns"]
    assert [i["id"] for c in mine for i in c["ideas"]] == [own]


# ── D. feedback list + submit ─────────────────────────────────────────────────


def test_ac_p_30_search_sort_and_closed(setup):
    s = setup
    a = _idea(s, 400, title="Order status tracking for dealers", upvotes=1)
    b = _idea(s, 401, title="Quotation knowledge capture", upvotes=3)
    r = _idea(s, 402, title="Rejected thing", status_key="rejected")
    h = _staff_session(s)
    c = s["client"]
    assert [i["id"] for i in c.get("/portal/ideas?q=quotation", headers=h).json()["items"]] == [b]
    assert [i["id"] for i in c.get("/portal/ideas?sort=top", headers=h).json()["items"]] == [b, a]
    assert r not in [i["id"] for i in c.get("/portal/ideas", headers=h).json()["items"]]
    closed = c.get("/portal/ideas?includeClosed=true", headers=h).json()["items"]
    assert r in [i["id"] for i in closed]
    only_rev = c.get("/portal/ideas?column=under_review", headers=h).json()
    assert only_rev["total"] == 2
    assert c.get("/portal/ideas?pageSize=500", headers=h).status_code == 422


def test_ac_p_31_submit_as_crm_user(setup):
    s = setup
    hc = _crm_session(s, sub="crm-sales-4")
    res = s["client"].post(
        "/portal/ideas",
        headers=hc,
        json={
            "title": "Order status tracking for dealers",
            "problem": "Dealers cannot track the status after they place an order.",
            "desiredOutcome": "See each order step.",
            "productId": s["product_id"],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["isMine"] is True
    assert body["statusLabel"] == "New"
    assert body["ideaNumber"]
    bad = s["client"].post("/portal/ideas", headers=hc, json={"title": "x", "problem": "", "productId": s["product_id"]})
    assert bad.status_code == 422


# ── E. changelog ──────────────────────────────────────────────────────────────


def test_ac_p_40_changelog_delivered_only(setup):
    s = setup
    d = _idea(s, 500, status_key="delivered", title="Spec sheet download")
    _idea(s, 501, status_key="building")
    res = s["client"].get("/portal/ideas/changelog", headers=_staff_session(s))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["id"] for i in items] == [d]
    assert items[0]["deliveredAt"]


def test_ac_p_41_changelog_note_managers_only(setup):
    s = setup
    d = _idea(s, 510, status_key="delivered")
    c = s["client"]
    restricted = _crm_session(s, sub="crm-sales-10", ideas_manage=False)
    assert c.put(f"/portal/ideas/{d}/note", headers=restricted, json={"note": "x"}).status_code == 403
    res = c.put(f"/portal/ideas/{d}/note", headers=_staff_session(s), json={"note": "  Spec sheets are live.  "})
    assert res.status_code == 200 and res.json()["note"] == "Spec sheets are live."
    items = c.get("/portal/ideas/changelog", headers=restricted).json()["items"]
    assert items[0]["note"] == "Spec sheets are live."
    assert c.put(f"/portal/ideas/{d}/note", headers=_staff_session(s), json={"note": "x" * 501}).status_code == 422


# ── F. idea page ──────────────────────────────────────────────────────────────


def test_ac_p_50_detail_shape_no_pii(setup):
    s = setup
    hc = _crm_session(s, sub="crm-sales-5")
    own = _idea(s, 600, crm_user="crm-sales-5", submitter_name="Aiman +60123456789")
    res = s["client"].get(f"/portal/ideas/{own}", headers=hc)
    assert res.status_code == 200, res.text
    d = res.json()
    for k in ("id", "ideaNumber", "title", "statusLabel", "statusColor", "column", "problem",
              "desiredOutcome", "useCases", "currentWorkaround", "submitterFirstName",
              "submittedAt", "productName", "upvotes", "myVote", "isMine", "timeline"):
        assert k in d, k
    for k in ("proposedSolution", "impact", "department", "rawText", "submitterContactId", "statusToken"):
        assert k not in d, k
    assert "6789" not in res.text  # a phone-shaped submitter name is never published
    assert d["isMine"] is True
    assert [t["label"] for t in d["timeline"]] == ["Under review", "Planned", "In progress", "Complete"]
    assert [t["state"] for t in d["timeline"]] == ["current", "upcoming", "upcoming", "upcoming"]


def test_ac_p_51_vote_toggle_distinct_principals(setup):
    s = setup
    iid = _idea(s, 700)
    c = s["client"]
    hs, hcrm = _staff_session(s), _crm_session(s)
    hc = _crm_session(s, sub="crm-sales-6")
    for h in (hs, hcrm, hc):
        r = c.post(f"/portal/ideas/{iid}/vote", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["myVote"] is True
    assert c.get(f"/portal/ideas/{iid}", headers=hs).json()["upvotes"] == 3
    r = c.post(f"/portal/ideas/{iid}/vote", headers=hc)
    assert r.json()["myVote"] is False and r.json()["upvotes"] == 2


def test_ac_p_51_vote_merged_child_resolves_to_survivor(setup):
    from modules.ideation.models import Idea

    s = setup
    survivor = _idea(s, 710)
    child = _idea(s, 711)
    db = s["factory"]()
    try:
        db.query(Idea).filter(Idea.id == child).first().merged_into_id = survivor
        db.commit()
    finally:
        db.close()
    r = s["client"].post(f"/portal/ideas/{child}/vote", headers=_staff_session(s))
    assert r.status_code == 409


def test_ac_p_52_voters_names_roles(setup):
    s = setup
    iid = _idea(s, 720)
    c = s["client"]
    from modules.ideation.models import IdeaVote

    hc = _crm_session(s, sub="crm-sales-7", name="Aiman Rahman")
    c.post(f"/portal/ideas/{iid}/vote", headers=hc)
    c.post(f"/portal/ideas/{iid}/vote", headers=_staff_session(s))
    # A legacy vote cast outside the portal (no stored name).
    db = s["factory"]()
    try:
        db.add(IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, voter_id="embed-user:legacy", dir="up"))
        db.commit()
    finally:
        db.close()
    res = c.get(f"/portal/ideas/{iid}/voters", headers=hc)
    assert res.status_code == 200, res.text
    voters = res.json()
    assert [v["role"] for v in voters] == ["Staff", "Staff", "Staff"]
    names = {v["name"] for v in voters}
    assert "Aiman" in names and None in names
    assert [v for v in voters if v["isMe"]][0]["name"] == "Aiman"
    assert "@" not in res.text


def test_ac_p_53_comments_likes_and_delete(setup):
    s = setup
    iid = _idea(s, 800)
    c = s["client"]
    hc = _crm_session(s, sub="crm-sales-8", name="Aiman Rahman", ideas_manage=False)
    hs = _staff_session(s)
    top = c.post(f"/portal/ideas/{iid}/comments", headers=hs, json={"body": "We will look at it."})
    assert top.status_code == 201, top.text
    reply = c.post(
        f"/portal/ideas/{iid}/comments", headers=hc, json={"body": "Thanks", "parentId": top.json()["id"]}
    )
    assert reply.status_code == 201
    like = c.post(f"/portal/ideas/{iid}/comments/{top.json()['id']}/like", headers=hc)
    assert like.status_code == 200 and like.json() == {"likeCount": 1, "likedByMe": True}
    rows = c.get(f"/portal/ideas/{iid}/comments", headers=hc).json()
    assert {r["authorName"] for r in rows} >= {"Aiman"}
    top_row = [r for r in rows if r["id"] == top.json()["id"]][0]
    assert top_row["likeCount"] == 1 and top_row["likedByMe"] is True
    assert top_row["authorRole"] == "Staff"
    # A non-manager cannot delete someone else's comment; a manager can.
    assert c.delete(f"/portal/ideas/{iid}/comments/{top.json()['id']}", headers=hc).status_code == 403
    assert c.delete(f"/portal/ideas/{iid}/comments/{reply.json()['id']}", headers=hs).status_code == 204
    unlike = c.post(f"/portal/ideas/{iid}/comments/{top.json()['id']}/like", headers=hc)
    assert unlike.json() == {"likeCount": 0, "likedByMe": False}


def test_ac_p_53_comment_validation_and_throttle(setup):
    s = setup
    iid = _idea(s, 810)
    hc = _crm_session(s, sub="crm-sales-9")
    c = s["client"]
    assert c.post(f"/portal/ideas/{iid}/comments", headers=hc, json={"body": ""}).status_code == 422
    assert c.post(f"/portal/ideas/{iid}/comments", headers=hc, json={"body": "x" * 2001}).status_code == 422
    codes = [c.post(f"/portal/ideas/{iid}/comments", headers=hc, json={"body": f"c{i}"}).status_code for i in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429


def test_ac_p_54_activity_feed(setup):
    from modules.ideation.models import IdeaStatusEvent

    s = setup
    iid = _idea(s, 900)
    db = s["factory"]()
    try:
        db.add(IdeaStatusEvent(
            tenant_id=DEFAULT_TENANT_ID, idea_id=iid, kind="status_changed",
            payload_json={"from_status_label": "New", "status_label": "Triaged"},
        ))
        db.commit()
    finally:
        db.close()
    from modules.ideation.services.portal import backfill_activity_from_status_events

    db = s["factory"]()
    try:
        backfill_activity_from_status_events(db)
        backfill_activity_from_status_events(db)  # idempotent
        db.commit()
    finally:
        db.close()
    c = s["client"]
    hs = _staff_session(s)
    c.post(f"/portal/ideas/{iid}/vote", headers=hs)
    cm = c.post(f"/portal/ideas/{iid}/comments", headers=hs, json={"body": "hello"}).json()
    c.post(f"/portal/ideas/{iid}/comments/{cm['id']}/like", headers=hs)
    res = c.get(f"/portal/ideas/{iid}/activity", headers=hs)
    assert res.status_code == 200, res.text
    kinds = [e["kind"] for e in res.json()]
    assert kinds.count("status_changed") == 1
    assert {"submitted", "status_changed", "comment", "upvotes", "comment_like"} <= set(kinds)
    assert kinds[-1] == "submitted"  # newest first
    sc = [e for e in res.json() if e["kind"] == "status_changed"][0]
    assert sc["fromLabel"] == "New" and sc["toLabel"] == "Triaged"
    asc = [e["kind"] for e in c.get(f"/portal/ideas/{iid}/activity?order=asc", headers=hs).json()]
    assert asc[0] == "submitted"


def test_ac_p_54_live_status_change_recorded(setup):
    from modules.ideation.services.portal import record_status_activity
    from modules.ideation.models import IdeaActivity

    s = setup
    iid = _idea(s, 910)
    db = s["factory"]()
    try:
        record_status_activity(db, tenant_id=DEFAULT_TENANT_ID, idea_id=iid, from_label="New", to_label="Triaged")
        db.commit()
        assert db.query(IdeaActivity).filter(IdeaActivity.idea_id == iid).count() == 1
    finally:
        db.close()


def test_ac_p_04_portal_token_never_authenticates_staff_endpoints(setup):
    s = setup
    h = _staff_session(s)
    assert s["client"].get("/auth/me", headers=h).status_code == 401
    assert s["client"].get("/ideation/ideas", headers=h).status_code == 401

"""IDEA-PORTAL - signed-in Canny-style idea portal (lane IDEA-PORTAL), RED first.

Contract: ``documentation/plans/sprint-5/idea-portal/acceptance-criteria.md``
(AC-P-xx ids below). Every ``/portal/ideas/*`` route needs a PORTAL token,
minted by one of three exchanges: staff (core login), crm (ideation embed
token), contact (chatbot link token + last 4 digits of the WhatsApp number).
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


def _crm_session(s, *, sub="crm-user-1", name="Alice Tan", product_id=None) -> dict:
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
    emb = s["client"].post("/embed/session", json={"connection_id": "sorento-portal", "assertion": a})
    assert emb.status_code == 200, emb.text
    embed_token = emb.json()["token"]
    res = s["client"].post("/portal/ideas/session/embed", json={"token": embed_token})
    assert res.status_code == 200, res.text
    assert res.json()["principal"]["kind"] == "crm"
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _contact(s, *, phone="+60123456789", first_name="Aiman Rahman") -> str:
    from modules.omnichannel.models import Contact, Workspace

    db = s["factory"]()
    try:
        ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name=first_name, phone=phone
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _idea(s, n, *, status_key="captured", token=None, contact_id=None, **kw):
    return _make_captured_idea(
        s["factory"],
        s["product_id"],
        idea_number=f"IDEA-{n:04d}",
        status_token=token,
        status_key=status_key,
        submitter_contact_id=contact_id,
        **kw,
    )


def _tok(c: str) -> str:
    return "plink_" + c * 18


def _link_session(s, token, last4, ip_headers=None):
    return s["client"].post(
        "/portal/ideas/session/link", json={"token": token, "last4": last4}, headers=ip_headers or {}
    )


def _contact_session(s, n=50, phone="+60123456789") -> tuple:
    cid = _contact(s, phone=phone)
    idea_id = _idea(s, n, token=_tok(chr(ord("a") + n % 26)), contact_id=cid)
    res = _link_session(s, _tok(chr(ord("a") + n % 26)), phone[-4:])
    assert res.status_code == 200, res.text
    assert res.json()["principal"]["kind"] == "contact"
    return {"Authorization": f"Bearer {res.json()['token']}"}, idea_id, cid


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
    assert me["kind"] == "crm" and me["name"] == "Alice"


def test_ac_p_02_bad_embed_token(setup):
    res = setup["client"].post("/portal/ideas/session/embed", json={"token": "nope"})
    assert res.status_code == 401


def test_ac_p_03_contact_link_session(setup):
    h, _, _ = _contact_session(setup)
    me = setup["client"].get("/portal/ideas/me", headers=h).json()
    assert me["kind"] == "contact"
    assert me["role"] == "Dealer"
    assert me["name"] == "Aiman"  # first token only, never the phone


@pytest.mark.parametrize("case", ["wrong", "unknown", "draft", "nocontact"])
def test_ac_p_03_link_failures_are_uniform(setup, case):
    s = setup
    cid = _contact(s)
    if case == "wrong":
        _idea(s, 51, token=_tok("w"), contact_id=cid)
        res = _link_session(s, _tok("w"), "0000")
    elif case == "unknown":
        res = _link_session(s, _tok("u"), "6789")
    elif case == "draft":
        _idea(s, 52, token=_tok("d"), contact_id=cid, status_key="draft")
        res = _link_session(s, _tok("d"), "6789")
    else:
        _idea(s, 53, token=_tok("n"))
        res = _link_session(s, _tok("n"), "6789")
    assert res.status_code == 401
    assert res.json() == {"error": {"code": "link_rejected", "message": "That number does not match this link."}}


def test_ac_p_03_link_attempts_throttled(setup):
    s = setup
    cid = _contact(s)
    _idea(s, 54, token=_tok("t"), contact_id=cid)
    codes = [_link_session(s, _tok("t"), "0000").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    # Even the right digits are refused while locked.
    locked = _link_session(s, _tok("t"), "6789")
    assert locked.status_code == 429
    assert locked.headers.get("retry-after")


def test_ac_p_03_bad_last4_shape_is_422(setup):
    assert _link_session(setup, _tok("x"), "12ab").status_code == 422


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


def test_ac_p_11_portal_hidden_only_staff_and_submitter(setup):
    from modules.ideation.models import Idea

    s = setup
    hc, own_idea, _ = _contact_session(s, n=60)
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
    hc, own, _ = _contact_session(s, n=80)
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


def test_ac_p_31_submit_as_contact(setup):
    s = setup
    hc, _, cid = _contact_session(s, n=90)
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


# ── F. idea page ──────────────────────────────────────────────────────────────


def test_ac_p_50_detail_shape_no_pii(setup):
    s = setup
    hc, own, _ = _contact_session(s, n=600)
    res = s["client"].get(f"/portal/ideas/{own}", headers=hc)
    assert res.status_code == 200, res.text
    d = res.json()
    for k in ("id", "ideaNumber", "title", "statusLabel", "statusColor", "column", "problem",
              "desiredOutcome", "useCases", "currentWorkaround", "submitterFirstName",
              "submittedAt", "productName", "upvotes", "myVote", "isMine", "timeline"):
        assert k in d, k
    for k in ("proposedSolution", "impact", "department", "rawText", "submitterContactId", "statusToken"):
        assert k not in d, k
    assert "6789" not in res.text
    assert d["isMine"] is True
    assert [t["label"] for t in d["timeline"]] == ["Under review", "Planned", "In progress", "Complete"]
    assert [t["state"] for t in d["timeline"]] == ["current", "upcoming", "upcoming", "upcoming"]


def test_ac_p_51_vote_toggle_distinct_principals(setup):
    s = setup
    iid = _idea(s, 700)
    c = s["client"]
    hs, hcrm = _staff_session(s), _crm_session(s)
    hc, _, _ = _contact_session(s, n=701)
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
    hc, _, _ = _contact_session(s, n=721)
    c.post(f"/portal/ideas/{iid}/vote", headers=hc)
    c.post(f"/portal/ideas/{iid}/vote", headers=_crm_session(s))
    c.post(f"/portal/ideas/{iid}/vote", headers=_staff_session(s))
    res = c.get(f"/portal/ideas/{iid}/voters", headers=hc)
    assert res.status_code == 200, res.text
    voters = res.json()
    assert sorted(v["role"] for v in voters) == ["Dealer", "Member", "Staff"]
    names = {v["role"]: v["name"] for v in voters}
    assert names["Dealer"] == "Aiman" and names["Member"] == "Alice"
    assert "@" not in res.text and "6789" not in res.text


def test_ac_p_53_comments_likes_and_delete(setup):
    s = setup
    iid = _idea(s, 800)
    c = s["client"]
    hc, _, _ = _contact_session(s, n=801)
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
    # A contact cannot delete staff's comment; staff can delete any.
    assert c.delete(f"/portal/ideas/{iid}/comments/{top.json()['id']}", headers=hc).status_code == 403
    assert c.delete(f"/portal/ideas/{iid}/comments/{reply.json()['id']}", headers=hs).status_code == 204
    unlike = c.post(f"/portal/ideas/{iid}/comments/{top.json()['id']}/like", headers=hc)
    assert unlike.json() == {"likeCount": 0, "likedByMe": False}


def test_ac_p_53_comment_validation_and_throttle(setup):
    s = setup
    iid = _idea(s, 810)
    hc, _, _ = _contact_session(s, n=811)
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

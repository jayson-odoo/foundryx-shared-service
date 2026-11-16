"""PUBLIC-IDEAS-BOARD - the existing idea portal opened to a contact through a
personal feedback link (no login). RED first.

Contract: ``documentation/plans/ideation/public-ideas-board/acceptance-criteria.md``
(AC-FB-xx ids below). Owner answers 15 Nov: link only, upvote + comment, no
submit, same set as the staff portal, link valid until staff cancel it.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_portal import _idea, _staff_session  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    ideation_client,
    setup,
)

UNAUTH = {"error": {"code": "unauthorized", "message": "Sign in to continue."}}


# ── helpers ───────────────────────────────────────────────────────────────────


def _contact(s, *, first_name="Dealer One", phone="+60123450001", tenant_id=DEFAULT_TENANT_ID) -> str:
    from modules.omnichannel.models import Contact, Workspace

    db = s["factory"]()
    try:
        ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id).first()
        c = Contact(tenant_id=tenant_id, workspace_id=ws.id, first_name=first_name, phone=phone)
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _link(s, contact_id, tenant_id=DEFAULT_TENANT_ID) -> str:
    from modules.ideation.services.feedback_links import get_or_create_link

    db = s["factory"]()
    try:
        row = get_or_create_link(db, tenant_id, contact_id)
        db.commit()
        return row.token
    finally:
        db.close()


def _cancel(s, contact_id, tenant_id=DEFAULT_TENANT_ID) -> None:
    from modules.ideation.services.feedback_links import cancel_links_for_contact

    db = s["factory"]()
    try:
        cancel_links_for_contact(db, tenant_id, contact_id)
        db.commit()
    finally:
        db.close()


def _exchange(s, token):
    return s["client"].post("/portal/ideas/session/link", json={"token": token})


def _contact_session(s, contact_id) -> dict:
    res = _exchange(s, _link(s, contact_id))
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _set(s, idea_id, **attrs) -> None:
    from modules.ideation.models import Idea

    db = s["factory"]()
    try:
        row = db.query(Idea).filter(Idea.id == idea_id).first()
        for k, v in attrs.items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


# ── A. the link ───────────────────────────────────────────────────────────────


def test_ac_fb_01_link_is_random_and_stable(setup):
    cid = _contact(setup)
    t1 = _link(setup, cid)
    t2 = _link(setup, cid)
    assert t1 == t2
    assert len(t1) >= 32 and t1.replace("-", "").replace("_", "").isalnum()
    other = _link(setup, _contact(setup, phone="+60123450002"))
    assert other != t1


def test_ac_fb_02_cancel_then_new_token(setup):
    cid = _contact(setup)
    old = _link(setup, cid)
    _cancel(setup, cid)
    assert _exchange(setup, old).status_code == 401
    new = _link(setup, cid)
    assert new != old
    assert _exchange(setup, new).status_code == 200
    assert _exchange(setup, old).status_code == 401


def test_ac_fb_03_contact_resolved_with_the_links_tenant(setup):
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS
    from app.models.tenant import Tenant
    from modules.ideation.models import IdeaContactLink
    from modules.omnichannel.models import Contact, Workspace

    s = setup
    db = s["factory"]()
    try:
        t = Tenant(name="Other Co", slug="other-feedback", status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE])
        db.add(t)
        db.flush()
        ws = Workspace(tenant_id=t.id, name="Other WS")
        db.add(ws)
        db.flush()
        foreign = Contact(tenant_id=t.id, workspace_id=ws.id, first_name="Other", phone="+60199990000")
        db.add(foreign)
        db.flush()
        # A planted row: default-tenant link pointing at another tenant's contact.
        db.add(IdeaContactLink(tenant_id=DEFAULT_TENANT_ID, contact_id=foreign.id, token="P" * 32))
        db.commit()
    finally:
        db.close()
    assert _exchange(s, "P" * 32).status_code == 401


# ── B. session ────────────────────────────────────────────────────────────────


def test_ac_fb_10_contact_principal(setup):
    cid = _contact(setup, first_name="Dealer One")
    h = _contact_session(setup, cid)
    me = setup["client"].get("/portal/ideas/me", headers=h).json()
    assert me == {"kind": "contact", "name": "Dealer", "role": "Dealer", "productId": None, "canManage": False}


@pytest.mark.parametrize("token", ["x" * 40, "short", "bad token with spaces!!", ""])
def test_ac_fb_11_bad_links_uniform_401(setup, token):
    res = _exchange(setup, token)
    assert res.status_code == 401
    assert res.json() == UNAUTH
    assert res.headers["Cache-Control"] == "no-store"
    assert res.headers["X-Robots-Tag"] == "noindex"
    assert res.headers["Referrer-Policy"] == "no-referrer"


def test_ac_fb_11_module_inactive_or_suspended_tenant(setup):
    from app.models.module import Module, TenantModule

    s = setup
    token = _link(s, _contact(s))
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
    assert _exchange(s, token).status_code == 401


def test_ac_fb_12_cancel_kills_live_session(setup):
    cid = _contact(setup)
    h = _contact_session(setup, cid)
    assert setup["client"].get("/portal/ideas/me", headers=h).status_code == 200
    _cancel(setup, cid)
    assert setup["client"].get("/portal/ideas/me", headers=h).status_code == 401


def test_ac_fb_12_contact_deleted_kills_session(setup):
    from modules.omnichannel.models import Contact

    cid = _contact(setup)
    h = _contact_session(setup, cid)
    db = setup["factory"]()
    try:
        db.query(Contact).filter(Contact.id == cid).delete()
        db.commit()
    finally:
        db.close()
    assert setup["client"].get("/portal/ideas/me", headers=h).status_code == 401


def test_ac_fb_13_failed_exchanges_throttled(setup):
    codes = [_exchange(setup, f"{'z' * 30}{i:04d}").status_code for i in range(25)]
    assert 429 in codes
    first = codes.index(429)
    assert all(c == 401 for c in codes[:first])
    res = _exchange(setup, "z" * 34)
    assert res.status_code == 429 and "Retry-After" in res.headers


def test_ac_fb_14_phone_shaped_name_never_published(setup):
    cid = _contact(setup, first_name="+60123450001")
    h = _contact_session(setup, cid)
    assert setup["client"].get("/portal/ideas/me", headers=h).json()["name"] is None


# ── C. what the contact sees and does ─────────────────────────────────────────


def test_ac_fb_20_all_is_the_staff_portal_set(setup):
    s = setup
    visible = _idea(s, 201, title="Remind me before a DO SLA breaches")
    _idea(s, 202, status_key="draft", title="draft")
    _idea(s, 203, is_test=True, title="test")
    hidden = _idea(s, 204, title="internal")
    _set(s, hidden, portal_hidden=True)
    child = _idea(s, 205, title="child")
    _set(s, child, merged_into_id=visible)
    h = _contact_session(s, _contact(s))
    ids = [i["id"] for i in s["client"].get("/portal/ideas", headers=h).json()["items"]]
    assert ids == [visible]
    road = s["client"].get("/portal/ideas/roadmap", headers=h).json()
    road_ids = [c["id"] for col in road["columns"] for c in col["ideas"]]
    assert road_ids == [visible]


def test_ac_fb_21_my_requests_by_contact_and_same_phone(setup):
    s = setup
    me = _contact(s, phone="+60123450001")
    twin = _contact(s, first_name="Dealer One", phone="+60 12-345 0001")  # same digits, other row
    stranger = _contact(s, first_name="Dealer One", phone="+60123459999")  # same NAME, other phone
    own = _idea(s, 211, submitter_contact_id=me)
    via_twin = _idea(s, 212, submitter_contact_id=twin)
    by_name = _idea(s, 213, submitter_contact_id=stranger)
    hidden_own = _idea(s, 214, submitter_contact_id=me)
    _set(s, hidden_own, portal_hidden=True)
    h = _contact_session(s, me)
    mine = {i["id"] for i in s["client"].get("/portal/ideas?mine=true", headers=h).json()["items"]}
    assert mine == {own, via_twin, hidden_own}
    cards = {i["id"]: i for i in s["client"].get("/portal/ideas", headers=h).json()["items"]}
    assert cards[own]["isMine"] and cards[via_twin]["isMine"]
    assert not cards[by_name]["isMine"]


def test_ac_fb_21_contact_without_phone_still_owns_its_ideas(setup):
    s = setup
    me = _contact(s, phone=None)
    own = _idea(s, 215, submitter_contact_id=me)
    h = _contact_session(s, me)
    mine = [i["id"] for i in s["client"].get("/portal/ideas?mine=true", headers=h).json()["items"]]
    assert mine == [own]


def test_ac_fb_21_no_requests_yet(setup):
    s = setup
    _idea(s, 216)
    h = _contact_session(s, _contact(s))
    body = s["client"].get("/portal/ideas?mine=true", headers=h).json()
    assert body["items"] == [] and body["total"] == 0


def test_ac_fb_22_one_vote_per_contact_shared_with_intake(setup):
    from modules.ideation.models import IdeaVote

    s = setup
    cid = _contact(s)
    iid = _idea(s, 221)
    h = _contact_session(s, cid)
    on = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()
    assert on["myVote"] is True and on["upvotes"] == 1
    db = s["factory"]()
    try:
        assert [v.voter_id for v in db.query(IdeaVote).filter(IdeaVote.idea_id == iid)] == [cid]
    finally:
        db.close()
    off = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()
    assert off["myVote"] is False and off["upvotes"] == 0
    voters_before = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h)
    assert voters_before.status_code == 200
    voters = s["client"].get(f"/portal/ideas/{iid}/voters", headers=h).json()
    assert voters == [{"name": "Dealer", "role": "Dealer", "isMe": True}]


def test_ac_fb_22_intake_vote_counts_as_the_contacts_vote(setup):
    from modules.ideation.models import IdeaVote

    s = setup
    cid = _contact(s)
    iid = _idea(s, 222, upvotes=1)
    db = s["factory"]()
    try:
        db.add(IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, voter_id=cid, dir="up"))
        db.commit()
    finally:
        db.close()
    h = _contact_session(s, cid)
    card = s["client"].get(f"/portal/ideas/{iid}", headers=h).json()
    assert card["myVote"] is True
    off = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()
    assert off == {"id": iid, "upvotes": 0, "myVote": False}


def test_ac_fb_23_comment_and_delete_own_only(setup):
    s = setup
    iid = _idea(s, 231)
    h = _contact_session(s, _contact(s, first_name="Dealer One"))
    staff = _staff_session(s)
    theirs = s["client"].post(f"/portal/ideas/{iid}/comments", headers=staff, json={"body": "From the team"})
    assert theirs.status_code == 201, theirs.text
    mine = s["client"].post(f"/portal/ideas/{iid}/comments", headers=h, json={"body": "Same here"})
    assert mine.status_code == 201, mine.text
    assert mine.json()["authorRole"] == "Dealer" and mine.json()["authorName"] == "Dealer"
    listed = {c["id"]: c for c in s["client"].get(f"/portal/ideas/{iid}/comments", headers=h).json()}
    assert listed[mine.json()["id"]]["isMine"] and listed[mine.json()["id"]]["authorRole"] == "Dealer"
    assert not listed[theirs.json()["id"]]["canDelete"]
    bad = s["client"].delete(f"/portal/ideas/{iid}/comments/{theirs.json()['id']}", headers=h)
    assert bad.status_code in (403, 404)
    ok = s["client"].delete(f"/portal/ideas/{iid}/comments/{mine.json()['id']}", headers=h)
    assert ok.status_code == 204


def test_ac_fb_24_no_submit_hide_or_note(setup):
    s = setup
    iid = _idea(s, 241)
    h = _contact_session(s, _contact(s))
    sub = s["client"].post(
        "/portal/ideas", headers=h, json={"title": "New", "problem": "x", "productId": s["product_id"]}
    )
    assert sub.status_code == 403
    assert s["client"].put(f"/portal/ideas/{iid}/hidden", headers=h, json={"hidden": True}).status_code == 403
    assert s["client"].put(f"/portal/ideas/{iid}/note", headers=h, json={"note": "x"}).status_code == 403


def test_ac_fb_25_detail_404s(setup):
    s = setup
    hidden = _idea(s, 251)
    _set(s, hidden, portal_hidden=True)
    draft = _idea(s, 252, status_key="draft")
    h = _contact_session(s, _contact(s))
    for iid in (hidden, draft, "no-such-id"):
        assert s["client"].get(f"/portal/ideas/{iid}", headers=h).status_code == 404


# ── D. links we send ──────────────────────────────────────────────────────────


def _board_link(s, idea_id):
    from modules.ideation.models import Idea
    from modules.ideation.services.feedback_links import mint_board_link

    db = s["factory"]()
    try:
        url = mint_board_link(db, db.query(Idea).filter(Idea.id == idea_id).first())
        db.commit()
        return url
    finally:
        db.close()


def test_ac_fb_30_board_link_shape(setup):
    from app.config import settings

    s = setup
    cid = _contact(s)
    iid = _idea(s, 301, submitter_contact_id=cid)
    url = _board_link(s, iid)
    token = _link(s, cid)
    assert url == f"{settings.frontend_url.rstrip('/')}/public/feedback/board/{token}/FB-0301"
    assert _board_link(s, _idea(s, 302)) is None


def test_ac_fb_30_board_link_on_crm_template_base(setup, monkeypatch):
    from modules.ideation.services import feedback_links

    s = setup
    cid = _contact(s)
    iid = _idea(s, 303, submitter_contact_id=cid)
    monkeypatch.setattr(
        feedback_links, "tenant_public_link_base", lambda db, tid: "https://crm.example.test/portal/ideas/{token}"
    )
    assert _board_link(s, iid) == f"https://crm.example.test/feedback/board/{_link(s, cid)}/FB-0303"


def test_ac_fb_30_board_link_plain_base(setup, monkeypatch):
    from modules.ideation.services import feedback_links

    s = setup
    cid = _contact(s)
    iid = _idea(s, 304, submitter_contact_id=cid)
    monkeypatch.setattr(feedback_links, "tenant_public_link_base", lambda db, tid: "https://ss.example.test/")
    assert _board_link(s, iid) == f"https://ss.example.test/public/feedback/board/{_link(s, cid)}/FB-0304"


def test_ac_fb_30_foreign_contact_gets_no_link(setup):
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS
    from app.models.tenant import Tenant
    from modules.omnichannel.models import Contact, Workspace

    s = setup
    db = s["factory"]()
    try:
        t = Tenant(name="Other Co", slug="other-feedback-2", status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE])
        db.add(t)
        db.flush()
        ws = Workspace(tenant_id=t.id, name="Other WS")
        db.add(ws)
        db.flush()
        foreign = Contact(tenant_id=t.id, workspace_id=ws.id, first_name="Other", phone="+60199990001")
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    finally:
        db.close()
    iid = _idea(s, 305, submitter_contact_id=foreign_id)
    assert _board_link(s, iid) is None


def test_ac_fb_31_status_event_carries_board_url(setup):
    from modules.ideation.models import IdeaStatusEvent

    s = setup
    cid = _contact(s)
    iid = _idea(s, 311, submitter_contact_id=cid)
    res = s["client"].post(f"/ideation/ideas/{iid}/status", headers=s["h"], json={"status": "triaged"})
    assert res.status_code == 200, res.text
    db = s["factory"]()
    try:
        payload = db.query(IdeaStatusEvent).filter(IdeaStatusEvent.idea_id == iid).one().payload_json
    finally:
        db.close()
    assert payload["board_url"].endswith(f"/public/feedback/board/{_link(s, cid)}/FB-0311")
    assert "/public/feedback/" in payload["track_url"]


def test_ac_fb_33_staff_cancel_endpoint(setup):
    s = setup
    cid = _contact(s)
    iid = _idea(s, 331, submitter_contact_id=cid)
    token = _link(s, cid)
    res = s["client"].post(f"/ideation/ideas/{iid}/feedback-link/cancel", headers=s["h"])
    assert res.status_code == 204, res.text
    assert _exchange(s, token).status_code == 401
    assert s["client"].post("/ideation/ideas/no-such/feedback-link/cancel", headers=s["h"]).status_code == 404
    # No submitter contact: nothing to cancel -> 404.
    bare = _idea(s, 332)
    assert s["client"].post(f"/ideation/ideas/{bare}/feedback-link/cancel", headers=s["h"]).status_code == 404
    assert s["client"].post(f"/ideation/ideas/{iid}/feedback-link/cancel").status_code == 401


def test_ac_fb_41_item_opens_by_number(setup):
    s = setup
    iid = _idea(s, 261)
    h = _contact_session(s, _contact(s))
    page = s["client"].get("/portal/ideas/IDEA-0261", headers=h)
    assert page.status_code == 200 and page.json()["id"] == iid
    assert s["client"].post("/portal/ideas/IDEA-0261/vote", headers=h).json()["myVote"] is True
    assert s["client"].get("/portal/ideas/IDEA-9999", headers=h).status_code == 404
    # Lane FEEDBACK-RENAME: the link now carries the shown number (FB-0261);
    # both forms resolve, so links already sent keep working.
    fb = s["client"].get("/portal/ideas/FB-0261", headers=h)
    assert fb.status_code == 200 and fb.json()["id"] == iid
    assert s["client"].get("/portal/ideas/fb-0261", headers=h).json()["id"] == iid


def test_ac_fb_32_whatsapp_reply_carries_the_board_link(setup):
    """The 'Track it here' reply is the personal board link when the idea has
    a submitter contact (asserted end to end in test_ideation_create_idea /
    test_ideation_intake_contract via ``_expected_board_link``); here: no
    contact = the old per-idea page, unchanged."""
    from app.config import settings
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    s = setup
    iid = _idea(s, 321, token="T" * 32)
    db = s["factory"]()
    try:
        idea = db.query(Idea).filter(Idea.id == iid).first()
        link = IntakeService(db)._contact_link(idea)
    finally:
        db.close()
    assert link == f"{settings.frontend_url.rstrip('/')}/public/feedback/{'T' * 32}"


def test_ac_fb_33_staff_grace_window_action_and_flag(setup):
    from modules.ideation.deferred_actions import IDEAS_CANCEL_FEEDBACK_LINK

    s = setup
    cid = _contact(s)
    iid = _idea(s, 333, submitter_contact_id=cid)
    bare = _idea(s, 334)
    got = s["client"].get(f"/ideation/ideas/{iid}", headers=s["h"]).json()
    assert got["hasSubmitterContact"] is True
    assert s["client"].get(f"/ideation/ideas/{bare}", headers=s["h"]).json()["hasSubmitterContact"] is False
    assert "submitterContactId" not in got
    token = _link(s, cid)
    db = s["factory"]()
    try:
        assert IDEAS_CANCEL_FEEDBACK_LINK.permission == "ideation.triage.manage"
        IDEAS_CANCEL_FEEDBACK_LINK.execute(db, DEFAULT_TENANT_ID, iid, {}, "")
    finally:
        db.close()
    assert _exchange(s, token).status_code == 401


# ── review round 1 ────────────────────────────────────────────────────────────


def test_rr1_b1_voter_without_contact_never_gets_the_authors_link(setup):
    from app.config import settings
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    s = setup
    author = _contact(s)
    candidate = _idea(s, 401, token="C" * 32, submitter_contact_id=author)
    db = s["factory"]()
    try:
        idea = db.query(Idea).filter(Idea.id == candidate).first()
        voter_without_contact = IntakeService(db)._contact_link(idea, recipient=None)
        other_voter = _contact(s, phone="+60123450777")
        voter_with_contact = IntakeService(db)._contact_link(idea, recipient=other_voter)
        db.commit()
    finally:
        db.close()
    assert voter_without_contact == f"{settings.frontend_url.rstrip('/')}/public/feedback/{'C' * 32}"
    assert _link(s, author) not in voter_with_contact
    assert voter_with_contact.endswith(f"/public/feedback/board/{_link(s, other_voter)}/FB-0401")


def test_tb_01_test_idea_mints_the_reporters_board_link(setup):
    """Lane FEEDBACK-TEST-BOARD-LINK (owner 17 Nov ~01:15, supersedes rr1): a
    Console test filing gets the reporter's personal board link like a real one."""
    from app.config import settings

    s = setup
    cid = _contact(s)
    iid = _idea(s, 402, is_test=True, submitter_contact_id=cid)
    url = _board_link(s, iid)
    assert url == f"{settings.frontend_url.rstrip('/')}/public/feedback/board/{_link(s, cid)}/FB-0402"


def test_tb_02_test_idea_without_contact_gets_no_link(setup):
    s = setup
    assert _board_link(s, _idea(s, 403, is_test=True)) is None


def test_tb_10_own_board_lists_own_test_items(setup):
    s = setup
    me = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    real = _idea(s, 404, submitter_contact_id=me)
    test_own = _idea(s, 405, is_test=True, submitter_contact_id=me)
    test_twin = _idea(s, 406, is_test=True, submitter_contact_id=twin)
    h = _contact_session(s, me)
    c = s["client"]
    every = {i["id"]: i for i in c.get("/portal/ideas", headers=h).json()["items"]}
    assert set(every) == {real, test_own, test_twin}
    assert every[test_own]["isMine"]
    mine = {i["id"] for i in c.get("/portal/ideas?mine=true", headers=h).json()["items"]}
    assert mine == {real, test_own, test_twin}
    road = c.get("/portal/ideas/roadmap", headers=h).json()
    assert {x["id"] for col in road["columns"] for x in col["ideas"]} == {real, test_own, test_twin}
    assert sum(col["count"] for col in road["columns"]) == 3
    # Opened by the number the link carries, and by id.
    for ref in ("FB-0405", test_own):
        d = c.get(f"/portal/ideas/{ref}", headers=h)
        assert d.status_code == 200, d.text
        assert d.json()["id"] == test_own and d.json()["problem"]
    assert c.post(f"/portal/ideas/{test_own}/comments", headers=h, json={"body": "ok"}).status_code == 201


def test_tb_11_other_contacts_never_see_a_test_item(setup):
    s = setup
    reporter = _contact(s, phone="+60123450001")
    other = _contact(s, first_name="Dealer One", phone="+60123459999")  # same name, other phone
    real = _idea(s, 407)
    test_item = _idea(s, 408, is_test=True, submitter_contact_id=reporter)
    h = _contact_session(s, other)
    c = s["client"]
    assert [i["id"] for i in c.get("/portal/ideas", headers=h).json()["items"]] == [real]
    body = c.get("/portal/ideas", headers=h).json()
    assert body["total"] == 1
    assert c.get("/portal/ideas?mine=true", headers=h).json()["items"] == []
    road = c.get("/portal/ideas/roadmap", headers=h).json()
    assert [x["id"] for col in road["columns"] for x in col["ideas"]] == [real]
    assert sum(col["count"] for col in road["columns"]) == 1
    for ref in (test_item, "FB-0408"):
        assert c.get(f"/portal/ideas/{ref}", headers=h).status_code == 404
    assert c.post(f"/portal/ideas/{test_item}/vote", headers=h).status_code == 404
    assert c.post(f"/portal/ideas/{test_item}/comments", headers=h, json={"body": "x"}).status_code == 404
    assert c.get(f"/portal/ideas/{test_item}/comments", headers=h).status_code == 404


def test_tb_12_staff_portal_never_sees_test_items(setup):
    s = setup
    cid = _contact(s)
    real = _idea(s, 409)
    test_item = _idea(s, 410, is_test=True, submitter_contact_id=cid)
    h = _staff_session(s)
    c = s["client"]
    assert [i["id"] for i in c.get("/portal/ideas", headers=h).json()["items"]] == [real]
    assert c.get(f"/portal/ideas/{test_item}", headers=h).status_code == 404


def test_tb_13_test_item_never_in_the_changelog(setup):
    s = setup
    me = _contact(s)
    real = _idea(s, 411, status_key="delivered", submitter_contact_id=me)
    test_item = _idea(s, 412, status_key="delivered", is_test=True, submitter_contact_id=me)
    h = _contact_session(s, me)
    c = s["client"]
    assert [i["id"] for i in c.get("/portal/ideas/changelog", headers=h).json()["items"]] == [real]
    # still on the reporter's own board list
    assert test_item in {i["id"] for i in c.get("/portal/ideas", headers=h).json()["items"]}


def test_tb_20_test_status_event_never_pokes_the_crm(setup, monkeypatch):
    from modules.ideation.models import IdeaStatusEvent
    from modules.ideation.services import status_events

    s = setup
    pokes = []
    monkeypatch.setattr(status_events, "queue_crm_poke", lambda *a, **k: pokes.append(a))
    cid = _contact(s)
    iid = _idea(s, 413, is_test=True, submitter_contact_id=cid)
    res = s["client"].post(f"/ideation/ideas/{iid}/status", headers=s["h"], json={"status": "triaged"})
    assert res.status_code == 200, res.text
    db = s["factory"]()
    try:
        ev = db.query(IdeaStatusEvent).filter(IdeaStatusEvent.idea_id == iid).one()
        assert ev.is_test is True and ev.payload_json["is_test"] is True
        assert ev.payload_json["board_url"].endswith(f"/public/feedback/board/{_link(s, cid)}/FB-0413")
    finally:
        db.close()
    assert pokes == []


def test_rr1_one_shot_response_keeps_the_per_idea_link(setup):
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    s = setup
    cid = _contact(s)
    iid = _idea(s, 403, token="O" * 32, submitter_contact_id=cid)
    db = s["factory"]()
    try:
        out = IntakeService(db)._one_shot_response(db.query(Idea).filter(Idea.id == iid).first())
    finally:
        db.close()
    assert out["link"].endswith(f"/public/feedback/{'O' * 32}")


def test_rr1_cancel_reaches_same_phone_siblings(setup):
    s = setup
    a = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 404, submitter_contact_id=a)
    ta, tt = _link(s, a), _link(s, twin)
    assert s["client"].post(f"/ideation/ideas/{iid}/feedback-link/cancel", headers=s["h"]).status_code == 204
    assert _exchange(s, ta).status_code == 401
    assert _exchange(s, tt).status_code == 401


def test_rr1_one_live_link_per_contact_enforced_by_the_db(setup):
    from sqlalchemy.exc import IntegrityError

    from modules.ideation.models import IdeaContactLink

    s = setup
    cid = _contact(s)
    _link(s, cid)
    db = s["factory"]()
    try:
        db.add(IdeaContactLink(tenant_id=DEFAULT_TENANT_ID, contact_id=cid, token="D" * 40))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_rr1_portal_token_subject_must_match_the_links_contact(setup):
    from modules.ideation.services.portal import KIND_CONTACT, PortalPrincipal, mint_portal_token

    s = setup
    a = _contact(s)
    b = _contact(s, phone="+60123450888")
    _link(s, a)
    res = _exchange(s, _link(s, a))
    from jose import jwt

    lid = jwt.get_unverified_claims(res.json()["token"])["lid"]
    forged = mint_portal_token(
        PortalPrincipal(tenant_id=DEFAULT_TENANT_ID, kind=KIND_CONTACT, subject=b, link_id=lid)
    )
    assert s["client"].get("/portal/ideas/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


# ── owner ruling (b): free text only on the dealer's own items ────────────────

# Strict (b): on another dealer's item ONLY title, status, steps, votes and
# comments - these keys never leave the server for it.
WITHHELD_KEYS = (
    "problem", "desiredOutcome", "useCases", "currentWorkaround",
    "submitterFirstName", "submittedAt", "productName",
)


def test_rb_full_text_only_on_own_items(setup):
    s = setup
    me = _contact(s)
    other = _contact(s, phone="+60123450999")
    own = _idea(s, 501, title="My item", problem="My own business detail", submitter_contact_id=me)
    theirs = _idea(s, 502, title="Their item", problem="Customer X pays 12% less", submitter_contact_id=other)
    untitled = _idea(s, 503, problem="Untitled secret problem text", submitter_contact_id=other)
    _set(s, theirs, desired_outcome="secret outcome", current_workaround="secret workaround", use_cases=["secret"])
    h = _contact_session(s, me)
    mine = s["client"].get(f"/portal/ideas/{own}", headers=h).json()
    assert mine["problem"] == "My own business detail"
    other_page = s["client"].get(f"/portal/ideas/{theirs}", headers=h).json()
    assert other_page["title"] == "Their item" and other_page["statusLabel"]
    # Fix round (crew-pass): the withheld keys are OMITTED, never sent as null.
    for key in WITHHELD_KEYS:
        assert key not in other_page, key
    assert other_page["timeline"] and "upvotes" in other_page
    # Own item keeps everything.
    for key in ("problem", "submitterFirstName", "submittedAt", "productName"):
        assert key in mine, key
    cards = {c["id"]: c for c in s["client"].get("/portal/ideas", headers=h).json()["items"]}
    assert cards[untitled]["title"] == "FB-0503"
    assert "secret" not in str(cards).lower()
    for key in ("submittedAt", "productName"):
        assert key not in cards[theirs], key
        assert key in cards[own], key
    # Review should-fix 3: roadmap + changelog cards omit them too.
    road = s["client"].get("/portal/ideas/roadmap", headers=h).json()
    road_cards = {c["id"]: c for col in road["columns"] for c in col["ideas"]}
    for key in ("submittedAt", "productName"):
        assert key not in road_cards[theirs], key
        assert key in road_cards[own], key
    _set(s, theirs, status_id=_status_id(s, "delivered"))
    log = {c["id"]: c for c in s["client"].get("/portal/ideas/changelog", headers=h).json()["items"]}
    for key in ("submittedAt", "productName"):
        assert key not in log[theirs], key
    # Staff still read everything.
    staff = s["client"].get(f"/portal/ideas/{theirs}", headers=_staff_session(s)).json()
    assert staff["problem"] == "Customer X pays 12% less"


def test_rb_search_never_probes_others_text(setup):
    s = setup
    me = _contact(s)
    other = _contact(s, phone="+60123450998")
    _idea(s, 511, title="Theirs", problem="needle in their text", submitter_contact_id=other)
    own = _idea(s, 512, title="Mine", problem="needle in my text", submitter_contact_id=me)
    by_title = _idea(s, 513, title="needle in a title")
    h = _contact_session(s, me)
    ids = {i["id"] for i in s["client"].get("/portal/ideas?q=needle", headers=h).json()["items"]}
    assert ids == {own, by_title}


def test_rb_strict_no_submitter_activity_on_others_items(setup):
    """Crew-pass fix (1): the 'Feedback submitted by <name> over WhatsApp'
    activity line is not returned for another dealer's item; staff and the
    dealer's own item keep it."""
    s = setup
    me = _contact(s)
    other = _contact(s, first_name="Other Dealer", phone="+60123450997")
    own = _idea(s, 521, submitter_contact_id=me)
    theirs = _idea(s, 522, submitter_contact_id=other)
    h = _contact_session(s, me)
    kinds = [e["kind"] for e in s["client"].get(f"/portal/ideas/{theirs}/activity", headers=h).json()]
    assert "submitted" not in kinds
    assert "submitted" in [e["kind"] for e in s["client"].get(f"/portal/ideas/{own}/activity", headers=h).json()]
    staff = s["client"].get(f"/portal/ideas/{theirs}/activity", headers=_staff_session(s)).json()
    assert "submitted" in [e["kind"] for e in staff]


def test_rb_one_vote_per_person_across_same_phone_contacts(setup):
    """Crew-pass fix (3): two contact rows with the same phone are ONE person,
    so a second link cannot add a second vote."""
    from modules.ideation.models import IdeaVote

    s = setup
    a = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 531)
    ha, ht = _contact_session(s, a), _contact_session(s, twin)
    on = s["client"].post(f"/portal/ideas/{iid}/vote", headers=ha).json()
    assert on["upvotes"] == 1 and on["myVote"] is True
    card = s["client"].get(f"/portal/ideas/{iid}", headers=ht).json()
    assert card["myVote"] is True  # the twin sees the person's vote as theirs
    off = s["client"].post(f"/portal/ideas/{iid}/vote", headers=ht).json()
    assert off == {"id": iid, "upvotes": 0, "myVote": False}
    again = s["client"].post(f"/portal/ideas/{iid}/vote", headers=ht).json()
    assert again["upvotes"] == 1
    assert s["client"].post(f"/portal/ideas/{iid}/vote", headers=ha).json()["upvotes"] == 0
    db = s["factory"]()
    try:
        assert db.query(IdeaVote).filter(IdeaVote.idea_id == iid, IdeaVote.dir == "up").count() == 0
    finally:
        db.close()
    voters_seen = s["client"].post(f"/portal/ideas/{iid}/vote", headers=ha)
    assert voters_seen.status_code == 200
    voters = s["client"].get(f"/portal/ideas/{iid}/voters", headers=ht).json()
    assert len(voters) == 1 and voters[0]["isMe"] is True


def test_rb_intake_vote_by_a_twin_counts_as_the_persons_vote(setup):
    from modules.ideation.models import IdeaVote

    s = setup
    a = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 532, upvotes=1)
    db = s["factory"]()
    try:
        db.add(IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, voter_id=twin, dir="up"))
        db.commit()
    finally:
        db.close()
    h = _contact_session(s, a)
    assert s["client"].get(f"/portal/ideas/{iid}", headers=h).json()["myVote"] is True
    off = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()
    assert off["upvotes"] == 0 and off["myVote"] is False



def _status_id(s, key):
    from modules.ideation.services.statuses import idea_status_id

    db = s["factory"]()
    try:
        return idea_status_id(db, key, DEFAULT_TENANT_ID)
    finally:
        db.close()


def test_rb_legacy_double_votes_collapse_on_toggle(setup):
    """Review should-fix 2: a person with up votes under two same-phone
    contacts (pre-lane data) is one 'on' vote; turning it off removes both."""
    from modules.ideation.models import IdeaVote

    s = setup
    a = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 541, upvotes=2)
    db = s["factory"]()
    try:
        for v in (a, twin):
            db.add(IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, voter_id=v, dir="up"))
        db.commit()
    finally:
        db.close()
    h = _contact_session(s, a)
    off = s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()
    assert off == {"id": iid, "upvotes": 0, "myVote": False}


def test_rb_whatsapp_vote_after_board_vote_is_not_a_second_vote(setup):
    """Review should-fix 1: a board vote, then a duplicate WhatsApp submission
    from the same phone on another contact row = still one vote."""
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    s = setup
    a = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 542)
    h = _contact_session(s, twin)
    assert s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).json()["upvotes"] == 1
    db = s["factory"]()
    try:
        IntakeService(db)._register_submitter_upvote(DEFAULT_TENANT_ID, iid, a)
        db.commit()
        assert db.query(Idea).filter(Idea.id == iid).first().upvotes == 1
    finally:
        db.close()

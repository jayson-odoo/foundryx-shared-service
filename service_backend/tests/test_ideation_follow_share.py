"""FEEDBACK-SUBSCRIBE - share one feedback item read-only, follow it for the
same WhatsApp status updates as the submitter. RED first.

Contract: ``documentation/plans/ideation/feedback-subscribe-behaviour-card.md``
(AC-FS-xx ids below). Only the parts no open owner question changes are here:
the follow table + follower feed rows, the share link + read-only share view,
staff add/remove follower, and the ONE shared phone normalisation. The phone
step (lookup + proof) waits on the owner's Q1-Q3.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_feedback_link import _contact, _contact_session, _set  # noqa: F401
from tests.test_ideation_portal import _idea, _staff_session  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    ideation_client,
    setup,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _foreign_contact(s) -> str:
    """A contact in another tenant (with its own workspace)."""
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS
    from app.models.tenant import Tenant
    from modules.omnichannel.models import Contact, Workspace

    db = s["factory"]()
    try:
        t = Tenant(name="Other Co", slug="other-follow", status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE])
        db.add(t)
        db.flush()
        ws = Workspace(tenant_id=t.id, name="Other WS")
        db.add(ws)
        db.flush()
        c = Contact(tenant_id=t.id, workspace_id=ws.id, first_name="Other", phone="+60123450009")
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _product_link(s, contact_id) -> str:
    """The contact's live board link for the setup product (one per product)."""
    from modules.ideation.services.feedback_links import get_or_create_link

    db = s["factory"]()
    try:
        row = get_or_create_link(db, DEFAULT_TENANT_ID, contact_id, s["product_id"])
        db.commit()
        return row.token
    finally:
        db.close()


def _move(s, iid, key="triaged"):
    res = s["client"].post(f"/ideation/ideas/{iid}/status", headers=s["h"], json={"status": key})
    assert res.status_code == 200, res.text


def _events(s, iid=None):
    from modules.ideation.models import IdeaStatusEvent

    db = s["factory"]()
    try:
        q = db.query(IdeaStatusEvent)
        if iid:
            q = q.filter(IdeaStatusEvent.idea_id == iid)
        return [r.payload_json for r in q.order_by(IdeaStatusEvent.seq).all()]
    finally:
        db.close()


def _follow(s, h, iid):
    return s["client"].post(f"/portal/ideas/{iid}/follow", headers=h)


def _unfollow(s, h, iid):
    return s["client"].delete(f"/portal/ideas/{iid}/follow", headers=h)


def _share_token(s, iid) -> str:
    res = s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"])
    assert res.status_code == 200, res.text
    url = res.json()["url"]
    assert "/public/feedback/share/" in url
    return url.rsplit("/", 1)[1]


# ── AC-FS-12: one shared phone normalisation ──────────────────────────────────


@pytest.mark.parametrize(
    "raw, digits",
    [
        ("+60 12-345 6789", "60123456789"),
        ("012-345 6789", "60123456789"),
        ("(012) 3456789", "60123456789"),
        ("60123456789", "60123456789"),
        ("", ""),
        ("12", ""),
    ],
)
def test_ac_fs_12_phone_normalisation(raw, digits):
    from modules.ideation.services.ownership import phone_digits

    assert phone_digits(raw) == digits


def test_ac_fs_12_local_zero_prefix_finds_the_e164_contact(setup):
    from modules.ideation.services.ownership import find_contacts_by_phone

    cid = _contact(setup, phone="+60123459876")
    db = setup["factory"]()
    try:
        found = [c.id for c in find_contacts_by_phone(db, DEFAULT_TENANT_ID, "012-345 9876")]
    finally:
        db.close()
    assert found == [cid]


# ── AC-FS-5: follow / unfollow ────────────────────────────────────────────────


def test_ac_fs_05_follow_unfollow_idempotent_with_count(setup):
    s = setup
    author = _contact(s, phone="+60123450001")
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 501, submitter_contact_id=author)
    h = _contact_session(s, fan)

    res = _follow(s, h, iid)
    assert res.status_code == 200, res.text
    assert res.json() == {"following": True, "followerCount": 1}
    assert _follow(s, h, iid).json() == {"following": True, "followerCount": 1}

    detail = s["client"].get(f"/portal/ideas/{iid}", headers=h).json()
    assert detail["following"] is True
    assert detail["followerCount"] == 1

    assert _unfollow(s, h, iid).json() == {"following": False, "followerCount": 0}
    assert _unfollow(s, h, iid).json() == {"following": False, "followerCount": 0}


def test_ac_fs_05_follow_does_not_vote(setup):
    s = setup
    fan = _contact(s, phone="+60123450002")
    iid = _idea(s, 502, submitter_contact_id=_contact(s))
    h = _contact_session(s, fan)
    _follow(s, h, iid)
    detail = s["client"].get(f"/portal/ideas/{iid}", headers=h).json()
    assert detail["myVote"] is False
    assert detail["upvotes"] == 0


def test_ac_fs_05_submitter_shows_as_following(setup):
    """The submitter is always followed (R8): his own item reads Following,
    without a follower row, and the count does not include him."""
    s = setup
    author = _contact(s)
    iid = _idea(s, 503, submitter_contact_id=author)
    detail = s["client"].get(f"/portal/ideas/{iid}", headers=_contact_session(s, author)).json()
    assert detail["following"] is True
    assert detail["followerCount"] == 0


def test_ac_fs_05_staff_session_cannot_self_follow(setup):
    s = setup
    iid = _idea(s, 504, submitter_contact_id=_contact(s))
    assert _follow(s, _staff_session(s), iid).status_code == 403


def test_ac_fs_05_test_item_cannot_be_followed(setup):
    s = setup
    fan = _contact(s, phone="+60123450002")
    iid = _idea(s, 505, submitter_contact_id=fan)
    _set(s, iid, is_test=True)
    res = _follow(s, _contact_session(s, fan), iid)
    assert res.status_code == 409
    assert res.json()["error"]["message"] == "Test items cannot be followed."


def test_share_live_fix_staff_cannot_add_a_follower_to_a_test_item_plain_words(setup):
    s = setup
    iid = _idea(s, 506, submitter_contact_id=_contact(s))
    _set(s, iid, is_test=True)
    res = s["client"].post(
        f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": _contact(s, phone="+60123450003")}
    )
    assert res.status_code == 409
    assert "Test items cannot be followed." in res.text


# ── AC-FS-6: followers get the status update ──────────────────────────────────


def test_ac_fs_06_follower_gets_own_row_with_own_board_link(setup):
    from tests.test_ideation_feedback_link import _link

    s = setup
    author = _contact(s, phone="+60123450001")
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 511, submitter_contact_id=author)
    _follow(s, _contact_session(s, fan), iid)
    _move(s, iid)

    rows = _events(s, iid)
    assert [(r["requester_phone"], r["recipient_role"]) for r in rows] == [
        ("+60123450001", "requester"),
        ("+60123450002", "follower"),
    ]
    # Links are per product since SS-MULTI-PRODUCT-BOARD: the item's product.
    assert rows[1]["board_url"].endswith(f"/public/feedback/board/{_product_link(s, fan)}/FB-0511")
    assert rows[0]["board_url"].endswith(f"/public/feedback/board/{_product_link(s, author)}/FB-0511")
    assert rows[1]["status_label"] == rows[0]["status_label"]


def test_ac_fs_06_one_message_per_person(setup):
    """A follower who is also the submitter (same phone, another contact row)
    gets no second copy."""
    s = setup
    author = _contact(s, phone="+60123450001")
    twin = _contact(s, phone="+60 12-345 0001")
    iid = _idea(s, 512, submitter_contact_id=author)
    _follow(s, _contact_session(s, twin), iid)
    _move(s, iid)
    assert [r["recipient_role"] for r in _events(s, iid)] == ["requester"]


def test_ac_fs_06_unfollowed_gets_nothing(setup):
    s = setup
    fan = _contact(s, phone="+60123450002")
    iid = _idea(s, 513, submitter_contact_id=_contact(s))
    h = _contact_session(s, fan)
    _follow(s, h, iid)
    _unfollow(s, h, iid)
    _move(s, iid)
    assert [r["recipient_role"] for r in _events(s, iid)] == ["requester"]


def test_ac_fs_06_follower_of_item_without_submitter_contact(setup):
    """An item staff typed in (no submitter contact) still updates its followers."""
    s = setup
    fan = _contact(s, phone="+60123450002")
    iid = _idea(s, 514)
    _follow(s, _contact_session(s, fan), iid)
    _move(s, iid)
    assert [(r["requester_phone"], r["recipient_role"]) for r in _events(s, iid)] == [
        ("+60123450002", "follower")
    ]


def test_ac_fs_06_merged_child_followers_follow_the_survivor(setup):
    """R10: a follower of a merged item gets the survivor's status update, and
    the merge notice itself."""
    s = setup
    fan = _contact(s, phone="+60123450002")
    survivor = _idea(s, 515, submitter_contact_id=_contact(s, phone="+60123450001"))
    child = _idea(s, 516, submitter_contact_id=_contact(s, phone="+60123450003"))
    _follow(s, _contact_session(s, fan), child)
    res = s["client"].post(
        "/ideation/ideas/merge", headers=s["h"], json={"survivorId": survivor, "ideaIds": [survivor, child]}
    )
    assert res.status_code == 200, res.text
    merged = [r for r in _events(s, child) if r["kind"] == "merged"]
    assert sorted((r["requester_phone"], r["recipient_role"]) for r in merged) == [
        ("+60123450002", "follower"),
        ("+60123450003", "requester"),
    ]

    _move(s, survivor)
    moved = [r for r in _events(s) if r["kind"] == "status_changed"]
    assert sorted((r["requester_phone"], r["recipient_role"]) for r in moved) == [
        ("+60123450001", "requester"),
        ("+60123450002", "follower"),
        ("+60123450003", "requester"),
    ]


def test_ac_fs_06_requester_rows_say_requester(setup):
    s = setup
    iid = _idea(s, 517, submitter_contact_id=_contact(s))
    _move(s, iid)
    assert _events(s, iid)[0]["recipient_role"] == "requester"


# ── AC-FS-7: staff add / remove follower ──────────────────────────────────────


def test_ac_fs_07_staff_add_list_remove(setup):
    s = setup
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 521, submitter_contact_id=_contact(s))
    c = s["client"]
    res = c.post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": fan})
    assert res.status_code == 200, res.text
    listed = c.get(f"/ideation/ideas/{iid}/followers", headers=s["h"]).json()
    assert [(f["contactId"], f["name"]) for f in listed] == [(fan, "Manager B")]
    # Idempotent.
    assert c.post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": fan}).status_code == 200
    assert len(c.get(f"/ideation/ideas/{iid}/followers", headers=s["h"]).json()) == 1

    assert c.delete(f"/ideation/ideas/{iid}/followers/{fan}", headers=s["h"]).status_code == 204
    assert c.get(f"/ideation/ideas/{iid}/followers", headers=s["h"]).json() == []


def test_ac_fs_07_foreign_tenant_contact_refused(setup):
    s = setup
    foreign = _foreign_contact(s)
    iid = _idea(s, 522)
    res = s["client"].post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": foreign})
    assert res.status_code == 422


def test_ac_fs_07_planted_foreign_follower_never_messaged(setup):
    """A follower row pointing at another tenant's contact resolves to nothing
    (stored ids resolved with the idea's tenant)."""
    from modules.ideation.models import IdeaFollower
    s = setup
    foreign = _foreign_contact(s)
    iid = _idea(s, 523)
    db = s["factory"]()
    try:
        db.add(IdeaFollower(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, contact_id=foreign))
        db.commit()
    finally:
        db.close()
    _move(s, iid)
    assert _events(s, iid) == []


# ── AC-FS-1/2: the share link ─────────────────────────────────────────────────


def test_ac_fs_01_share_link_stable_until_stopped(setup):
    s = setup
    iid = _idea(s, 531, submitter_contact_id=_contact(s))
    t1 = _share_token(s, iid)
    assert _share_token(s, iid) == t1
    assert s["client"].delete(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 204
    assert s["client"].get(f"/portal/ideas/shared/{t1}").status_code == 404
    t2 = _share_token(s, iid)
    assert t2 != t1


def test_ac_fs_01_contact_can_share_from_the_board(setup):
    s = setup
    author = _contact(s)
    iid = _idea(s, 532, submitter_contact_id=author)
    res = s["client"].post(f"/portal/ideas/{iid}/share", headers=_contact_session(s, author))
    assert res.status_code == 200, res.text
    assert res.json()["url"].rsplit("/", 1)[1] == _share_token(s, iid)


def test_ac_fs_01_test_item_has_no_share_link(setup):
    s = setup
    iid = _idea(s, 533, submitter_contact_id=_contact(s))
    _set(s, iid, is_test=True)
    res = s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"])
    assert res.status_code == 409
    assert "Test items cannot be shared." in res.text


def test_share_live_fix_own_test_item_on_the_board_says_why_and_flags_it(setup):
    """crew s4: a contact's own TRUE test item (listed as Yours) is flagged
    ``isTest`` on the item page (the board hides Share/Follow), and a Share call
    is refused in plain words, never "Feedback not found."."""
    s = setup
    author = _contact(s)
    iid = _idea(s, 544, submitter_contact_id=author)
    _set(s, iid, is_test=True)
    h = _contact_session(s, author)
    detail = s["client"].get(f"/portal/ideas/{iid}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["isTest"] is True
    res = s["client"].post(f"/portal/ideas/{iid}/share", headers=h)
    assert res.status_code == 409
    assert res.json()["error"]["message"] == "Test items cannot be shared."


def test_share_live_fix_real_item_is_not_flagged_test(setup):
    s = setup
    author = _contact(s)
    iid = _idea(s, 545, submitter_contact_id=author)
    assert s["client"].get(f"/portal/ideas/{iid}", headers=_contact_session(s, author)).json()["isTest"] is False


def test_share_link_opens_on_the_crm_host_for_a_crm_tenant(setup, monkeypatch):
    """Lane FEEDBACK-SHARE-SS-HOST: a tenant whose public links go to the CRM
    (template base) gets its share link on the CRM host, like its board links
    (``{crm origin}/feedback/share/<token>``); the CRM page frames this
    frontend's share page."""
    from app.config import settings
    from modules.ideation.services import feedback_links

    monkeypatch.setattr(
        feedback_links, "tenant_public_link_base", lambda db, tid: "https://crm.example.test/portal/ideas/{token}"
    )
    monkeypatch.setattr(settings, "frontend_url", "https://ss.example.test/")
    s = setup
    iid = _idea(s, 540, submitter_contact_id=_contact(s))
    url = s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).json()["url"]
    assert url.startswith("https://crm.example.test/feedback/share/")
    token = url.rsplit("/", 1)[1]
    assert s["client"].get(f"/portal/ideas/shared/{token}").status_code == 200
    author = _contact(s)
    iid2 = _idea(s, 542, submitter_contact_id=author)
    res = s["client"].post(f"/portal/ideas/{iid2}/share", headers=_contact_session(s, author))
    assert res.json()["url"].startswith("https://crm.example.test/feedback/share/")
    assert feedback_links.board_base(None, "t").startswith("https://crm.example.test/feedback/board")


def test_share_live_fix_plain_tenant_base_is_the_ss_frontend(setup, monkeypatch):
    from modules.ideation.services import feedback_links

    monkeypatch.setattr(feedback_links, "tenant_public_link_base", lambda db, tid: "https://ss.tenant.test/")
    s = setup
    iid = _idea(s, 541, submitter_contact_id=_contact(s))
    url = s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).json()["url"]
    assert url.startswith("https://ss.tenant.test/public/feedback/share/")


def test_ac_fs_02_share_view_read_only_no_phones(setup):
    s = setup
    author = _contact(s, first_name="Dealer One", phone="+60123450001")
    iid = _idea(s, 534, submitter_contact_id=author)
    _follow(s, _contact_session(s, _contact(s, phone="+60123450002")), iid)
    token = _share_token(s, iid)
    c = s["client"]
    res = c.get(f"/portal/ideas/shared/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == iid
    assert body["followerCount"] == 1
    assert body["following"] is False
    assert body["myVote"] is False
    assert body["isMine"] is False
    assert "+60123450001" not in res.text and "60123450001" not in res.text
    assert res.headers["cache-control"] == "no-store"
    assert c.get(f"/portal/ideas/shared/{token}/comments").status_code == 200
    assert c.get(f"/portal/ideas/shared/{token}/activity").status_code == 200


@pytest.mark.parametrize("token", ["short", "x" * 43, "..%2F..%2Fetc"])
def test_ac_fs_02_bad_share_token_uniform_404(setup, token):
    res = setup["client"].get(f"/portal/ideas/shared/{token}")
    assert res.status_code == 404


def test_ac_fs_02_hidden_item_share_view_404(setup):
    s = setup
    iid = _idea(s, 535, submitter_contact_id=_contact(s))
    token = _share_token(s, iid)
    _set(s, iid, portal_hidden=True)
    assert s["client"].get(f"/portal/ideas/shared/{token}").status_code == 404


def test_ac_fs_02_share_token_is_not_a_portal_session(setup):
    """The share token never authorises a write."""
    s = setup
    iid = _idea(s, 536, submitter_contact_id=_contact(s))
    token = _share_token(s, iid)
    h = {"Authorization": f"Bearer {token}"}
    assert s["client"].post(f"/portal/ideas/{iid}/vote", headers=h).status_code == 401
    assert s["client"].post(f"/portal/ideas/{iid}/follow", headers=h).status_code == 401


# ── AC-FS-3/4: the phone step (owner Q1 a WhatsApp code, Q2 a stop; crew
#    contract: SS makes + checks the code, the product only looks the phone up
#    and delivers the code over its existing template) ──────────────────────────

import json  # noqa: E402

import httpx  # noqa: E402

PRODUCT_BASE = "https://crm.example.test"
PRODUCT_KEY = "product-test-key-not-real"


@pytest.fixture
def product(monkeypatch):
    """The item's product answering lookup / send-code (mock transport). The
    delivered codes land in ``state["codes"]``."""
    from modules.ideation.services import phone_verify

    state = {"requests": [], "lookup": 200, "send": 202, "name": "Manager B", "codes": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/contacts/lookup"):
            if state["lookup"] == 200:
                return httpx.Response(200, json={"contactId": "crm-77", "name": state["name"], "phone": body["phone"]})
            return httpx.Response(state["lookup"], json={})
        state["codes"].append(body["code"])
        return httpx.Response(state["send"], json={})

    monkeypatch.setattr(phone_verify, "_transport", httpx.MockTransport(handler))
    return state


def _product_connection(s, *, product_id=None, provider="sorento"):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    db = s["factory"]()
    try:
        cfg = {"baseUrl": PRODUCT_BASE}
        if product_id:
            cfg["productId"] = product_id
        conn = Connection(
            tenant_id=DEFAULT_TENANT_ID,
            provider=provider,
            type="consumer",
            name="Product",
            config_json=cfg,
            credentials_json=encrypt_secret({"apiKey": PRODUCT_KEY}),
            is_active=True,
        )
        db.add(conn)
        db.commit()
    finally:
        db.close()


def _send(s, token, phone):
    return s["client"].post(f"/portal/ideas/shared/{token}/phone/send-code", json={"phone": phone})


def _verify(s, token, phone, code):
    return s["client"].post(f"/portal/ideas/shared/{token}/phone/verify", json={"phone": phone, "code": code})


def _shared_item(s, n):
    iid = _idea(s, n, submitter_contact_id=_contact(s, phone="+60123450001"))
    return iid, _share_token(s, iid)


def _prove(s, product, token, phone):
    assert _send(s, token, phone).status_code == 200
    res = _verify(s, token, phone, product["codes"][-1])
    assert res.status_code == 200, res.text
    return res.json()


def test_ac_fs_03_send_code_looks_up_then_delivers_a_code(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 541)
    res = _send(s, token, "012-345 0002")
    assert res.status_code == 200, res.text
    assert res.json() == {"sent": True}
    lookup, send = product["requests"]
    assert str(lookup.url) == f"{PRODUCT_BASE}/api/v1/external/ideation/contacts/lookup"
    assert json.loads(lookup.content) == {"phone": "+60123450002", "phoneDigits": "60123450002"}
    assert str(send.url) == f"{PRODUCT_BASE}/api/v1/external/ideation/phone/send-code"
    body = json.loads(send.content)
    assert body["phone"] == "+60123450002" and len(body["code"]) == 6 and body["code"].isdigit()
    assert lookup.headers["X-API-Key"] == PRODUCT_KEY


def test_ac_fs_03_code_never_stored_in_clear(setup, product):
    from modules.ideation.models import IdeaPhoneCode

    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 553)
    _send(s, token, "+60123450002")
    db = s["factory"]()
    try:
        row = db.query(IdeaPhoneCode).one()
    finally:
        db.close()
    assert product["codes"][0] not in row.code_hash


def test_ac_fs_03_unknown_phone_names_the_product_and_sends_nothing(setup, product):
    s = setup
    _product_connection(s)
    product["lookup"] = 404
    _iid, token = _shared_item(s, 542)
    res = _send(s, token, "+60123450002")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "not_registered"
    assert "Sorento CRM" in err["message"]
    assert product["codes"] == []


def test_ac_fs_03_junk_phone_422_without_calling_the_product(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 543)
    assert _send(s, token, "12ab").status_code == 422
    assert product["requests"] == []


def test_ac_fs_03_no_product_connection_is_a_retryable_error(setup, product):
    s = setup
    _iid, token = _shared_item(s, 544)
    res = _send(s, token, "+60123450002")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "unavailable"


NOT_SET_UP = "Phone check is not set up for this product yet."


def test_lookup_403_says_phone_check_not_set_up(setup, product):
    """The CRM refuses the lookup (integration user lacks the permission):
    a distinct message, never the generic "try again", and no code sent."""
    s = setup
    _product_connection(s)
    product["lookup"] = 403
    _iid, token = _shared_item(s, 560)
    res = _send(s, token, "+60123450002")
    assert res.status_code == 503
    err = res.json()["error"]
    assert err["code"] == "not_set_up"
    assert err["message"] == NOT_SET_UP
    assert product["codes"] == []


def test_send_code_403_says_phone_check_not_set_up_and_voids_the_code(setup, product):
    from modules.ideation.models import IdeaPhoneCode

    s = setup
    _product_connection(s)
    product["send"] = 403
    _iid, token = _shared_item(s, 561)
    res = _send(s, token, "+60123450002")
    assert res.status_code == 503
    assert res.json()["error"] == {**res.json()["error"], "code": "not_set_up", "message": NOT_SET_UP}
    db = s["factory"]()
    try:
        assert all(r.used_at is not None for r in db.query(IdeaPhoneCode).all())
    finally:
        db.close()


def test_no_connection_logs_why_without_secrets(setup, product, caplog):
    import logging

    s = setup
    _iid, token = _shared_item(s, 562)
    with caplog.at_level(logging.WARNING, logger="modules.ideation.services.phone_verify"):
        res = _send(s, token, "+60123450002")
    assert res.status_code == 503
    text = caplog.text
    assert "no active consumer connection" in text
    assert PRODUCT_KEY not in text and "60123450002" not in text


def test_lookup_refusal_logs_the_http_status(setup, product, caplog):
    import logging

    s = setup
    _product_connection(s)
    product["lookup"] = 403
    _iid, token = _shared_item(s, 563)
    with caplog.at_level(logging.WARNING, logger="modules.ideation.services.phone_verify"):
        _send(s, token, "+60123450002")
    assert "lookup refused: HTTP 403" in caplog.text
    assert PRODUCT_KEY not in caplog.text


def test_ac_fs_03_undelivered_code_is_dead(setup, product):
    s = setup
    _product_connection(s)
    product["send"] = 500
    _iid, token = _shared_item(s, 545)
    assert _send(s, token, "+60123450002").status_code == 503
    assert _verify(s, token, "+60123450002", product["codes"][0]).status_code == 400


def test_ac_fs_03_another_products_connection_is_never_used(setup, product):
    """Multi-product: a consumer connection tagged for ANOTHER product never
    answers for this item."""
    s = setup
    from tests.test_ideation_public_status import _create_software_product

    other = _create_software_product(s["client"], s["h"], name="EcoHub")
    _product_connection(s, product_id=other, provider="ecohub")
    _iid, token = _shared_item(s, 546)
    assert _send(s, token, "+60123450002").status_code == 503
    assert product["requests"] == []


def test_ac_fs_03_connection_tagged_for_the_items_product(setup, product):
    s = setup
    _product_connection(s, product_id=s["product_id"])
    _iid, token = _shared_item(s, 552)
    assert _send(s, token, "+60123450002").status_code == 200


def test_ac_fs_03_throttled(setup, product, monkeypatch):
    from app.config import settings

    s = setup
    _product_connection(s)
    monkeypatch.setattr(settings, "throttle_idea_follow_phone_max", 2)
    _iid, token = _shared_item(s, 547)
    assert _send(s, token, "+60123450002").status_code == 200
    assert _send(s, token, "+60123450002").status_code == 200
    assert _send(s, token, "+60123450002").status_code == 429


def test_ac_fs_04_verify_gives_own_session_and_follow_works(setup, product):
    s = setup
    _product_connection(s)
    iid, token = _shared_item(s, 548)
    body = _prove(s, product, token, "012-345 0002")
    assert body["principal"]["kind"] == "contact"
    assert body["principal"]["name"] == "Manager"
    assert "/public/feedback/board/" in body["boardUrl"] and body["boardUrl"].endswith("/FB-0548")
    h = {"Authorization": f"Bearer {body['token']}"}
    assert _follow(s, h, iid).json() == {"following": True, "followerCount": 1}

    # The SS contact was created for the WhatsApp updates.
    _move(s, iid)
    assert [(r["requester_phone"], r["recipient_role"]) for r in _events(s, iid)] == [
        ("+60123450001", "requester"),
        ("+60123450002", "follower"),
    ]


def test_ac_fs_04_code_is_single_use(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 554)
    _prove(s, product, token, "+60123450002")
    assert _verify(s, token, "+60123450002", product["codes"][-1]).status_code == 400


def test_ac_fs_04_new_code_cancels_the_old(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 555)
    _send(s, token, "+60123450002")
    _send(s, token, "+60123450002")
    old, new = product["codes"]
    if old != new:
        assert _verify(s, token, "+60123450002", old).status_code == 400
    assert _verify(s, token, "+60123450002", new).status_code == 200


def test_ac_fs_04_five_wrong_codes_end_it(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 556)
    _send(s, token, "+60123450002")
    good = product["codes"][0]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        res = _verify(s, token, "+60123450002", bad)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "wrong_code"
    assert _verify(s, token, "+60123450002", good).json()["error"]["code"] == "code_expired"


def test_ac_fs_04_expired_code(setup, product):
    from datetime import datetime, timedelta, timezone

    from modules.ideation.models import IdeaPhoneCode

    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 557)
    _send(s, token, "+60123450002")
    db = s["factory"]()
    try:
        db.query(IdeaPhoneCode).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    res = _verify(s, token, "+60123450002", product["codes"][0])
    assert res.json()["error"]["code"] == "code_expired"


def test_ac_fs_04_code_bound_to_its_phone(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 558)
    _send(s, token, "+60123450002")
    assert _verify(s, token, "+60123450003", product["codes"][0]).status_code == 400


def test_ac_fs_04_verify_reuses_the_existing_contact(setup, product):
    s = setup
    _product_connection(s)
    existing = _contact(s, first_name="Known", phone="+60123450002")
    iid, token = _shared_item(s, 549)
    body = _prove(s, product, token, "0123450002")
    h = {"Authorization": f"Bearer {body['token']}"}
    _follow(s, h, iid)
    listed = s["client"].get(f"/ideation/ideas/{iid}/followers", headers=s["h"]).json()
    assert [f["contactId"] for f in listed] == [existing]


def test_ac_fs_04_the_submitter_lands_as_himself(setup, product):
    s = setup
    _product_connection(s)
    iid, token = _shared_item(s, 551)
    body = _prove(s, product, token, "+60123450001")
    h = {"Authorization": f"Bearer {body['token']}"}
    detail = s["client"].get(f"/portal/ideas/{iid}", headers=h).json()
    assert detail["isMine"] is True
    assert detail["following"] is True


# ── review round 1 ────────────────────────────────────────────────────────────


def test_rr1_follower_row_never_carries_the_submitters_status_page(setup):
    """The per-item status page lets its holder comment AS the submitter and
    read the submitter's full text: a follower's row must not carry it."""
    s = setup
    fan = _contact(s, phone="+60123450002")
    iid = _idea(s, 561, submitter_contact_id=_contact(s, phone="+60123450001"))
    _follow(s, _contact_session(s, fan), iid)
    _move(s, iid)
    requester, follower = _events(s, iid)
    assert requester["track_url"]
    assert follower["track_url"] is None
    assert follower["board_url"]


def test_rr1_undelivered_code_after_timeout_is_dead(setup, monkeypatch):
    from modules.ideation.services import phone_verify

    s = setup
    _product_connection(s)
    codes = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/contacts/lookup"):
            return httpx.Response(200, json={"contactId": "x", "name": "B", "phone": body["phone"]})
        codes.append(body["code"])
        raise httpx.ReadTimeout("slow", request=request)

    monkeypatch.setattr(phone_verify, "_transport", httpx.MockTransport(handler))
    _iid, token = _shared_item(s, 562)
    assert _send(s, token, "+60123450002").status_code == 503
    assert _verify(s, token, "+60123450002", codes[0]).status_code == 400


def test_rr1_phone_throttle_is_per_tenant():
    """A phone hammered in one tenant never locks it in another."""
    from modules.ideation.services.phone_verify import _phone_key

    assert _phone_key("t1", "60123450002") != _phone_key("t2", "60123450002")


# ── crew pass 70e96f2b ────────────────────────────────────────────────────────


def test_cp1_staff_cannot_add_the_submitter_as_a_follower(setup):
    """The submitter already gets every update (R8) and never has a row: adding
    them (or a same-phone sibling contact) is a 422 with a plain reason."""
    s = setup
    author = _contact(s, phone="+60123450001")
    twin = _contact(s, first_name="Twin", phone="+60 12-345 0001")
    iid = _idea(s, 571, submitter_contact_id=author)
    c = s["client"]
    for cid in (author, twin):
        res = c.post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": cid})
        assert res.status_code == 422, res.text
        assert "already" in res.text
    assert c.get(f"/ideation/ideas/{iid}/followers", headers=s["h"]).json() == []


def test_cp1_verified_session_is_the_items_product_link(setup, product):
    """After #252 a contact holds one live link per product: the phone step's
    session must be the item's product link, the same one its board link opens."""
    s = setup
    _product_connection(s)
    iid, token = _shared_item(s, 572)
    body = _prove(s, product, token, "+60123450002")
    assert body["principal"]["productId"] == s["product_id"]
    assert f"/board/{body['boardUrl'].split('/board/')[1].split('/')[0]}" in body["boardUrl"]


# Lane FEEDBACK-COMMENT-PHONE-LIKE-PORTAL: the phone step's messages read like
# the CRM sign-in (codes unchanged). Every number here is made up.
def test_wrong_code_counts_down_the_tries_left_like_the_crm(setup, product):
    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 590)
    _send(s, token, "+60123450002")
    good = product["codes"][0]
    bad = "000000" if good != "000000" else "111111"
    msgs = [_verify(s, token, "+60123450002", bad).json()["error"]["message"] for _ in range(5)]
    assert msgs == [
        "That code is not right. 4 tries left.",
        "That code is not right. 3 tries left.",
        "That code is not right. 2 tries left.",
        "That code is not right. 1 try left.",
        "That code is not right.",
    ]


def test_expired_code_reads_like_the_crm(setup, product):
    from datetime import datetime, timedelta, timezone

    from modules.ideation.models import IdeaPhoneCode

    s = setup
    _product_connection(s)
    _iid, token = _shared_item(s, 591)
    _send(s, token, "+60123450002")
    db = s["factory"]()
    try:
        db.query(IdeaPhoneCode).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    res = _verify(s, token, "+60123450002", product["codes"][0])
    assert res.json()["error"] == {"code": "code_expired", "message": "That code has expired. Send a new one."}


def test_throttled_phone_step_names_the_minutes_like_the_crm(setup, product, monkeypatch):
    from app.config import settings

    s = setup
    _product_connection(s)
    monkeypatch.setattr(settings, "throttle_idea_follow_phone_max", 1)
    _iid, token = _shared_item(s, 592)
    assert _send(s, token, "+60123450002").status_code == 200
    res = _send(s, token, "+60123450002")
    assert res.status_code == 429
    # 429 wire unchanged: {detail} + Retry-After; only the words follow the CRM.
    minutes = -(-int(res.headers["Retry-After"]) // 60)
    assert res.json()["detail"] == f"Too many tries. Try again in {minutes} minute{'' if minutes == 1 else 's'}."

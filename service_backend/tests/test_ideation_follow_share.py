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
    assert _follow(s, _contact_session(s, fan), iid).status_code == 404


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
    assert rows[1]["board_url"].endswith(f"/public/feedback/board/{_link(s, fan)}/FB-0511")
    assert rows[0]["board_url"].endswith(f"/public/feedback/board/{_link(s, author)}/FB-0511")
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
    assert s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 404


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


@pytest.mark.parametrize("token", ["", "short", "x" * 43, "../../etc"])
def test_ac_fs_02_bad_share_token_uniform_404(setup, token):
    assert setup["client"].get(f"/portal/ideas/shared/{token}").status_code in (404, 405)


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

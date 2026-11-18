"""Lane FEEDBACK-WA-TEST-FLAG: staff turn a wrongly flagged test item into a
real one ("Mark as real item").

A real person's filing that arrived flagged ``is_test`` (an older chatbot
console turn, before the caller was fixed) hides Share and Follow for good,
because nothing could clear the flag. ``POST /ideation/ideas/{id}/mark-real``
(``ideation.triage.manage``) clears it, puts the item at the bottom of the real
priority lane, writes one History row, and from then on the item shares and
follows like any real item. Merged groups move together; an item linked to a
test business requirement is refused (a real item may never sit on a test BR).

Test-first: written before the endpoint exists.
"""
from tests.test_ideation_feedback_link import _contact, _contact_session, _set  # noqa: F401
from tests.test_ideation_ideas_actions import _make_user
from tests.test_ideation_portal import _idea  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    ideation_client,
    setup,
)


def _mark(s, iid, h=None):
    return s["client"].post(f"/ideation/ideas/{iid}/mark-real", headers=h or s["h"])


def _row(s, iid):
    from modules.ideation.models import Idea

    db = s["factory"]()
    try:
        r = db.query(Idea).filter(Idea.id == iid).first()
        return {"is_test": r.is_test, "priority": r.priority, "merged_into_id": r.merged_into_id}
    finally:
        db.close()


def _real_lane_next(s) -> int:
    from app.models import DEFAULT_TENANT_ID
    from modules.ideation.services.ideas import next_capture_priority

    db = s["factory"]()
    try:
        return next_capture_priority(db, DEFAULT_TENANT_ID, is_test=False)
    finally:
        db.close()


def test_mark_real_clears_the_flag_and_returns_the_item(setup):
    s = setup
    iid = _idea(s, 801, submitter_contact_id=_contact(s))
    _set(s, iid, is_test=True)
    res = _mark(s, iid)
    assert res.status_code == 200, res.text
    assert res.json()["isTest"] is False
    assert _row(s, iid)["is_test"] is False


def test_mark_real_then_share_and_follow_work(setup):
    s = setup
    author = _contact(s)
    iid = _idea(s, 802, submitter_contact_id=author)
    _set(s, iid, is_test=True)
    assert s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 409
    assert _mark(s, iid).status_code == 200
    assert s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 200
    detail = s["client"].get(f"/portal/ideas/{iid}", headers=_contact_session(s, author))
    assert detail.status_code == 200, detail.text
    assert detail.json()["isTest"] is False


def test_mark_real_lands_at_the_bottom_of_the_real_lane(setup):
    s = setup
    _idea(s, 803)  # an existing real item
    iid = _idea(s, 804)
    _set(s, iid, is_test=True, priority=1)
    expected = _real_lane_next(s)
    assert _mark(s, iid).status_code == 200
    assert _row(s, iid)["priority"] == expected


def test_mark_real_is_in_history_with_who(setup):
    s = setup
    iid = _idea(s, 805)
    _set(s, iid, is_test=True)
    assert _mark(s, iid).status_code == 200
    rows = s["client"].get(f"/ideation/ideas/{iid}/history", headers=s["h"]).json()
    top = rows[0]
    assert (top["action"], top["from"], top["to"]) == ("Marked as real item", "Test item", "Real item")
    assert top["who"]


def test_mark_real_on_a_real_item_is_refused_plainly(setup):
    s = setup
    iid = _idea(s, 806)
    res = _mark(s, iid)
    assert res.status_code == 409
    assert "already a real item" in res.text
    rows = s["client"].get(f"/ideation/ideas/{iid}/history", headers=s["h"]).json()
    assert all(r["action"] != "Marked as real item" for r in rows)


def test_mark_real_merged_child_is_refused(setup):
    s = setup
    survivor = _idea(s, 807)
    child = _idea(s, 808)
    _set(s, survivor, is_test=True)
    _set(s, child, is_test=True, merged_into_id=survivor)
    res = _mark(s, child)
    assert res.status_code == 409
    assert "merged into" in res.text
    assert _row(s, child)["is_test"] is True


def test_mark_real_survivor_takes_its_merged_children_along(setup):
    s = setup
    survivor = _idea(s, 809)
    child = _idea(s, 810)
    _set(s, survivor, is_test=True)
    _set(s, child, is_test=True, merged_into_id=survivor)
    assert _mark(s, survivor).status_code == 200
    assert _row(s, survivor)["is_test"] is False
    assert _row(s, child)["is_test"] is False
    assert _row(s, child)["merged_into_id"] == survivor


def test_mark_real_refused_while_linked_to_a_test_br(setup):
    from app.models import DEFAULT_TENANT_ID
    from modules.ideation.models import BusinessRequirement, IdeaBusinessRequirement

    s = setup
    iid = _idea(s, 811)
    _set(s, iid, is_test=True)
    db = s["factory"]()
    try:
        br = BusinessRequirement(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id="any-status",
            template_key="br",
            template_version=1,
            title="Test BR",
            is_test=True,
        )
        db.add(br)
        db.flush()
        db.add(IdeaBusinessRequirement(tenant_id=DEFAULT_TENANT_ID, idea_id=iid, business_requirement_id=br.id))
        db.commit()
    finally:
        db.close()
    res = _mark(s, iid)
    assert res.status_code == 409
    assert "test business requirement" in res.text
    assert _row(s, iid)["is_test"] is True


def test_mark_real_unknown_item_404(setup):
    assert _mark(setup, "not-an-idea").status_code == 404


def test_mark_real_needs_triage_permission(setup):
    s = setup
    iid = _idea(s, 812)
    _set(s, iid, is_test=True)
    _make_user(s["factory"], "viewer-mr@example.com", "Viewer1234!", ["ideation.ideas.read"])
    h = _auth(s["client"], email="viewer-mr@example.com", password="Viewer1234!")
    assert _mark(s, iid, h).status_code == 403
    assert _row(s, iid)["is_test"] is True

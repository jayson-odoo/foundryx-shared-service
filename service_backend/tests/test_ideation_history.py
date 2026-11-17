"""FEEDBACK-SUBSCRIBE crew pass c4572865: the operator feedback record gets a
History tab (owner standing rule: every tracked action on a record shows in its
History - who, on behalf of, when, plain action, old -> new). RED first.

``GET /ideation/ideas/{id}/history`` lists, newest first: status moves (the
existing ``idea_activity`` rows, now with who moved it), staff field edits,
follower added / removed (staff or the contact themselves), share link created
and stopped. Tenant-scoped; gated ``ideation.ideas.view``.
"""
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_feedback_link import _contact, _contact_session  # noqa: F401
from tests.test_ideation_follow_share import _foreign_contact, _move  # noqa: F401
from tests.test_ideation_portal import _idea  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    ideation_client,
    setup,
)


def _history(s, iid, h=None):
    res = s["client"].get(f"/ideation/ideas/{iid}/history", headers=h or s["h"])
    assert res.status_code == 200, res.text
    return res.json()


def _actions(rows):
    return [(r["action"], r["from"], r["to"]) for r in rows]


def test_hist_01_status_move_shows_who_and_old_new(setup):
    s = setup
    iid = _idea(s, 601, submitter_contact_id=_contact(s))
    _move(s, iid)
    rows = _history(s, iid)
    assert rows[0]["action"] == "Status changed"
    assert rows[0]["from"] and rows[0]["to"] and rows[0]["from"] != rows[0]["to"]
    assert rows[0]["who"]  # the staff user who moved it
    assert rows[0]["at"].endswith("Z")


def test_hist_02_followers_and_share_are_recorded(setup):
    s = setup
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 602, submitter_contact_id=_contact(s))
    c = s["client"]
    assert c.post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": fan}).status_code == 200
    assert c.delete(f"/ideation/ideas/{iid}/followers/{fan}", headers=s["h"]).status_code == 204
    assert c.post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 200
    assert c.post(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 200  # same link: no 2nd row
    assert c.delete(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 204
    rows = _history(s, iid)
    assert _actions(rows) == [
        ("Share link stopped", None, None),
        ("Share link created", None, None),
        ("Follower removed", "Manager B", None),
        ("Follower added", None, "Manager B"),
    ]
    assert all(r["who"] for r in rows)


def test_hist_03_contact_self_follow_is_recorded_as_them(setup):
    s = setup
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 603, submitter_contact_id=_contact(s))
    h = _contact_session(s, fan)
    s["client"].post(f"/portal/ideas/{iid}/follow", headers=h)
    s["client"].delete(f"/portal/ideas/{iid}/follow", headers=h)
    rows = _history(s, iid)
    assert _actions(rows) == [("Follower removed", "Manager B", None), ("Follower added", None, "Manager B")]
    assert {r["who"] for r in rows} == {"Manager B"}


def test_hist_04_staff_edit_records_old_and_new(setup):
    s = setup
    iid = _idea(s, 604, submitter_contact_id=_contact(s))
    res = s["client"].patch(f"/ideation/ideas/{iid}", headers=s["h"], json={"title": "Order tracking v2"})
    assert res.status_code == 200, res.text
    row = _history(s, iid)[0]
    assert row["action"] == "Title edited"
    assert row["to"] == "Order tracking v2"


def test_hist_05_no_edit_row_when_nothing_changed(setup):
    s = setup
    iid = _idea(s, 605, submitter_contact_id=_contact(s))
    s["client"].patch(f"/ideation/ideas/{iid}", headers=s["h"], json={"title": "Same"})
    s["client"].patch(f"/ideation/ideas/{iid}", headers=s["h"], json={"title": "Same"})
    assert [r["action"] for r in _history(s, iid)].count("Title edited") == 1


def test_hist_06_tenant_scoped_and_404(setup):
    s = setup
    assert s["client"].get("/ideation/ideas/not-an-idea/history", headers=s["h"]).status_code == 404


def test_hist_07_rows_carry_no_ids(setup):
    """Plain words only: no contact ids / UUIDs in the history text."""
    s = setup
    fan = _contact(s, first_name="Manager B", phone="+60123450002")
    iid = _idea(s, 607, submitter_contact_id=_contact(s))
    s["client"].post(f"/ideation/ideas/{iid}/followers", headers=s["h"], json={"contactId": fan})
    body = str(_history(s, iid))
    assert fan not in body and iid not in body


# ── crew pass 5441b840: every tracked staff action reaches History ───────────


def test_hist_08_cancel_feedback_link_endpoint_is_recorded(setup):
    s = setup
    iid = _idea(s, 611, submitter_contact_id=_contact(s, first_name="Dealer One"))
    assert s["client"].post(f"/ideation/ideas/{iid}/feedback-link/cancel", headers=s["h"]).status_code == 204
    row = _history(s, iid)[0]
    assert (row["action"], row["from"], row["to"]) == ("Feedback link cancelled", "Dealer One", None)
    assert row["who"]


def test_hist_09_cancel_feedback_link_deferred_action_is_recorded(setup):
    """The item's "Cancel feedback link" runs through the grace-window action."""
    from app.models.user import User
    from modules.ideation.deferred_actions import _ideas_cancel_feedback_link

    s = setup
    iid = _idea(s, 612, submitter_contact_id=_contact(s, first_name="Dealer One"))
    db = s["factory"]()
    try:
        user = db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()
        _ideas_cancel_feedback_link(db, DEFAULT_TENANT_ID, iid, {}, user.id)
        db.commit()
        name = user.name
    finally:
        db.close()
    row = _history(s, iid)[0]
    assert (row["action"], row["from"], row["who"]) == ("Feedback link cancelled", "Dealer One", name)


def test_hist_10_merge_and_unmerge_are_recorded_on_both_items(setup):
    s = setup
    survivor = _idea(s, 613)
    child = _idea(s, 614)
    c = s["client"]
    assert c.post(
        "/ideation/ideas/merge", headers=s["h"], json={"survivorId": survivor, "ideaIds": [survivor, child]}
    ).status_code == 200
    assert _actions(_history(s, survivor))[0] == ("Merged in", None, "FB-0614")
    assert _actions(_history(s, child))[0] == ("Merged into", None, "FB-0613")
    assert c.post(f"/ideation/ideas/{child}/unmerge", headers=s["h"]).status_code == 200
    assert _actions(_history(s, survivor))[0] == ("Unmerged", "FB-0614", None)
    assert _actions(_history(s, child))[0] == ("Unmerged", "FB-0613", None)


def test_hist_11_attachment_added_is_recorded(setup):
    s = setup
    iid = _idea(s, 615)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    res = s["client"].post(
        f"/ideation/ideas/{iid}/attachments",
        headers=s["h"],
        files={"file": ("shot.png", png, "application/octet-stream")},
    )
    assert res.status_code in (200, 201), res.text
    assert _actions(_history(s, iid))[0] == ("Attachment added", None, "shot.png")


def test_hist_12_linked_to_business_requirement_is_recorded(setup):
    from tests.test_ideation_br import _FULL_ANSWERS

    s = setup
    iid = _idea(s, 616)
    br = s["client"].post(
        "/ideation/business-requirements",
        headers=s["h"],
        json={"productId": s["product_id"], "answers": _FULL_ANSWERS, "ideaIds": [iid]},
    )
    assert br.status_code in (200, 201), br.text
    row = _history(s, iid)[0]
    assert row["action"] == "Linked to business requirement"
    assert row["to"]
    assert br.json()["id"] not in str(row)

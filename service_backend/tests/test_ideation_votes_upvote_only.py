"""Plan 19 - upvote-only voting (AC-19-12..14), RED tests written before the code."""
import re

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_embed_writes import (  # noqa: F401
    _auth,
    _bearer,
    _create_software_product,
    _insert_idea,
    _mint,
    _seed_connection,
    ideation_client,
)


def _operator_user_id(factory):
    from app.models import User
    from tests.conftest import ACTIVE_EMAIL

    db = factory()
    try:
        return db.query(User).filter(User.email == ACTIVE_EMAIL).one().id
    finally:
        db.close()


def _seed_vote(factory, idea_id, voter_id, dir):
    from modules.ideation.models import Idea, IdeaVote

    db = factory()
    try:
        db.add(IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=idea_id, voter_id=voter_id, dir=dir))
        idea = db.get(Idea, idea_id)
        idea.upvotes = db.query(IdeaVote).filter_by(idea_id=idea_id, dir="up").count() + (
            1 if dir == "up" else 0
        )
        idea.downvotes = 1 if dir == "down" else 0
        db.commit()
    finally:
        db.close()


@pytest.fixture
def op(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    return {
        "c": ideation_client,
        "h": h,
        "pid": pid,
        "idea": _insert_idea(ideation_client._factory, pid, problem="votable"),
    }


# ── AC-19-12 ──────────────────────────────────────────────────────────────────
def test_ac_19_12_operator_down_is_422_and_changes_nothing(op):
    res = op["c"].post(f"/ideation/ideas/{op['idea']}/vote", headers=op["h"], json={"dir": "down"})
    assert res.status_code == 422, res.text
    got = op["c"].get(f"/ideation/ideas/{op['idea']}", headers=op["h"]).json()
    assert got["upvotes"] == 0 and got["myVote"] is None


def test_ac_19_12_operator_up_toggles(op):
    url = f"/ideation/ideas/{op['idea']}/vote"
    on = op["c"].post(url, headers=op["h"], json={"dir": "up"})
    assert on.status_code == 200 and on.json()["upvotes"] == 1 and on.json()["myVote"] == "up"
    off = op["c"].post(url, headers=op["h"], json={"dir": "up"})
    assert off.json()["upvotes"] == 0 and off.json()["myVote"] is None


def test_ac_19_12_existing_down_row_switched_to_up_by_upvote(op):
    c, f, idea = op["c"], op["c"]._factory, op["idea"]
    _seed_vote(f, idea, _operator_user_id(f), "down")
    res = c.post(f"/ideation/ideas/{idea}/vote", headers=op["h"], json={"dir": "up"})
    assert res.status_code == 200, res.text
    assert res.json()["upvotes"] == 1
    assert res.json()["downvotes"] == 0
    assert res.json()["myVote"] == "up"


def test_ac_19_12_embed_down_is_422(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _seed_connection(ideation_client._factory, product_id=pid)
    idea = _insert_idea(ideation_client._factory, pid)
    b = _bearer(_mint(ideation_client))
    res = ideation_client.post(f"/embed/ideas/{idea}/vote", headers=b, json={"dir": "down"})
    assert res.status_code == 422, res.text
    up = ideation_client.post(f"/embed/ideas/{idea}/vote", headers=b, json={"dir": "up"})
    assert up.status_code == 200 and up.json()["upvotes"] == 1


# ── AC-19-13 ──────────────────────────────────────────────────────────────────
def test_ac_19_13_down_rows_ignored_in_tallies_and_my_vote(op):
    c, f, idea = op["c"], op["c"]._factory, op["idea"]
    _seed_vote(f, idea, _operator_user_id(f), "down")
    _seed_vote(f, idea, "someone-else", "down")
    got = c.get(f"/ideation/ideas/{idea}", headers=op["h"]).json()
    assert got["downvotes"] == 0
    assert got["upvotes"] == 0
    assert got["myVote"] is None  # caller's row is 'down' -> reads null
    listed = c.get("/ideation/ideas", headers=op["h"]).json()
    row = next(r for r in listed if r["id"] == idea)
    assert row["downvotes"] == 0 and row["myVote"] is None


def test_ac_19_13_other_voters_up_counts_with_down_present(op):
    c, f, idea = op["c"], op["c"]._factory, op["idea"]
    _seed_vote(f, idea, "down-voter", "down")
    c.post(f"/ideation/ideas/{idea}/vote", headers=op["h"], json={"dir": "up"})
    got = c.get(f"/ideation/ideas/{idea}", headers=op["h"]).json()
    assert got["upvotes"] == 1 and got["downvotes"] == 0 and got["myVote"] == "up"


def test_ac_19_13_recount_zeroes_downvotes_column_and_keeps_rows(op):
    from modules.ideation.models import Idea, IdeaVote
    from modules.ideation.services.actions import IdeaActionService

    c, f, idea = op["c"], op["c"]._factory, op["idea"]
    _seed_vote(f, idea, "down-voter", "down")
    db = f()
    try:
        row = db.get(Idea, idea)
        row.downvotes = 5  # stale legacy tally
        IdeaActionService(db)._recount(row)
        assert row.downvotes == 0
        assert row.upvotes == 0
        db.commit()
        assert db.query(IdeaVote).filter(IdeaVote.idea_id == idea, IdeaVote.dir == "down").count() == 1
    finally:
        db.close()


def test_ac_19_13_embed_wire_downvotes_zero(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _seed_connection(ideation_client._factory, product_id=pid)
    idea = _insert_idea(ideation_client._factory, pid)
    _seed_vote(ideation_client._factory, idea, "embed-user:user-1", "down")
    b = _bearer(_mint(ideation_client, sub="user-1"))
    got = ideation_client.get(f"/embed/ideas/{idea}", headers=b).json()
    assert got["downvotes"] == 0 and got["myVote"] is None


# ── AC-19-14 ──────────────────────────────────────────────────────────────────
def test_ac_19_14_issue_body_lists_upvotes_only(ideation_client, monkeypatch):
    from modules.ideation.models import Idea
    from tests.ideation_build_helpers import FakeGitHub, sendable_setup
    from tests.test_ideation_send_to_build import _body_of_send
    from tests.test_ideation_br import _idea

    s = sendable_setup(ideation_client)
    idea_id = _idea(ideation_client, s["h"], s["pid"], "Export orders to CSV")
    db = ideation_client._factory()
    try:
        idea = db.get(Idea, idea_id)
        idea.idea_number = "IDEA-0042"
        idea.upvotes, idea.downvotes = 4, 2
        db.commit()
    finally:
        db.close()
    res = ideation_client.post(
        f"/ideation/business-requirements/{s['br_id']}/ideas",
        headers=s["h"],
        json={"ideaIds": [idea_id]},
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    section = body.split("## Linked ideas", 1)[1].split("\n## ", 1)[0]
    assert "IDEA-0042" in section
    assert "+4" in section
    assert not re.search(r"/\s*-\d", section), section

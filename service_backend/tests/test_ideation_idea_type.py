"""SS-IDEA-TYPE - a real ``type`` on ideas (``idea`` | ``issue``).

The WhatsApp complaint path (a system issue / feature request) rides the SAME
intake as ideas; only the classification differs. Allowed values come from ONE
table (``app_ideation.idea_types``); a missing type = ``idea``; an unknown type is
a typed 422. Read/list return ``type``; the list filters by it (multi-value).
Statuses / triage permissions / status updates are untouched.

Red-first: written before the implementation.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_create_idea import (  # noqa: F401 - fixtures reused
    _FULL_FIELDS,
    _auth,
    _create_idea,
    _key_auth,
    ideation_client,
    setup,
)
from tests.test_ideation_embed_writes import _bearer, _mint, _seed_connection


def _idea_row(factory, idea_id):
    from modules.ideation.models import Idea

    db = factory()
    try:
        return db.query(Idea).filter(Idea.id == idea_id).first()
    finally:
        db.close()


# ── catalog ───────────────────────────────────────────────────────────────────


def test_catalog_seeded_with_idea_default_and_issue(setup):
    from modules.ideation.services.idea_types import default_idea_type, list_idea_types

    db = setup["factory"]()
    try:
        keys = [t.key for t in list_idea_types(db)]
        assert keys == ["idea", "issue"]
        assert default_idea_type(db) == "idea"
    finally:
        db.close()


def test_new_type_is_a_row_not_a_path(setup):
    """Adding a type = inserting a row; intake accepts it with no code change."""
    from modules.ideation.models import IdeaType

    db = setup["factory"]()
    try:
        db.add(IdeaType(key="question", label="Question", sort_order=2, is_default=False))
        db.commit()
    finally:
        db.close()
    res = _create_idea(
        setup["client"], setup["key"], setup["contact_id"], setup["product_id"],
        type="question",
    )
    assert res.status_code == 200, res.text
    assert _idea_row(setup["factory"], res.json()["draft_id"]).type == "question"


# ── intake create (WhatsApp path) ─────────────────────────────────────────────


def _one_shot(c, key, pid, **over):
    body = {
        "product_id": pid,
        "problem": over.pop("problem", "Orders page crashes on save"),
        "title": "Orders crash",
        "submitter_crm_user_id": "crm-1",
        "submitter_phone": "+60100000001",
    }
    body.update(over)
    return c.post("/ideation/intake/ideas", headers=_key_auth(key), json=body)


def test_one_shot_without_type_defaults_to_idea(setup):
    res = _one_shot(setup["client"], setup["key"], setup["product_id"])
    assert res.status_code == 201, res.text
    assert res.json()["type"] == "idea"
    assert _idea_row(setup["factory"], res.json()["idea_id"]).type == "idea"


def test_one_shot_issue_stored_and_echoed(setup):
    res = _one_shot(setup["client"], setup["key"], setup["product_id"], type="issue")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["type"] == "issue"
    assert body["status"] == "captured"
    assert _idea_row(setup["factory"], body["idea_id"]).type == "issue"


def test_one_shot_unknown_type_is_422_and_creates_nothing(setup):
    from tests.test_ideation_create_idea import _idea_count

    before = _idea_count(setup["factory"])
    res = _one_shot(setup["client"], setup["key"], setup["product_id"], type="complaint")
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "unknown_type"
    assert _idea_count(setup["factory"]) == before


def test_one_shot_type_is_case_insensitive(setup):
    res = _one_shot(setup["client"], setup["key"], setup["product_id"], type=" Issue ")
    assert res.status_code == 201, res.text
    assert res.json()["type"] == "issue"


def test_similar_own_type_lane(setup):
    c, key, pid = setup["client"], setup["key"], setup["product_id"]
    text = "Let CS export orders to Excel from the list"
    a = _one_shot(c, key, pid, problem=text).json()["idea_id"]
    b = _one_shot(c, key, pid, problem=text, type="issue").json()["idea_id"]
    body = {"product_id": pid, "text": text, "submitter_crm_user_id": "crm-1"}
    url = "/ideation/intake/ideas/similar-own"
    both = c.post(url, headers=_key_auth(key), json=body).json()["matches"]
    assert {m["idea_id"] for m in both} == {a, b}
    assert {m["idea_id"]: m["type"] for m in both} == {a: "idea", b: "issue"}
    only = c.post(url, headers=_key_auth(key), json={**body, "type": "issue"}).json()
    assert [m["idea_id"] for m in only["matches"]] == [b]


def test_turn_flow_issue_stored_kept_and_reply_says_issue(setup):
    c, key, cid, pid = setup["client"], setup["key"], setup["contact_id"], setup["product_id"]
    r1 = _create_idea(c, key, cid, pid, type="issue", message_text="Orders page crashes on save")
    assert r1.status_code == 200, r1.text
    draft_id = r1.json()["draft_id"]
    assert _idea_row(setup["factory"], draft_id).type == "issue"
    # Continuation turns without ``type`` keep it (never silently reset to idea).
    r2 = _create_idea(c, key, cid, pid, draft_id=draft_id, fields=_FULL_FIELDS, skip=["impact", "proposed_solution"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "review", r2.json()
    r3 = _create_idea(c, key, cid, pid, draft_id=draft_id, confirm=True)
    assert r3.json()["status"] == "complete", r3.json()
    assert "Issue " in r3.json()["reply_text"]
    assert _idea_row(setup["factory"], draft_id).type == "issue"


def test_turn_flow_idea_reply_unchanged(setup):
    c, key, cid, pid = setup["client"], setup["key"], setup["contact_id"], setup["product_id"]
    r1 = _create_idea(c, key, cid, pid, fields=_FULL_FIELDS)
    r2 = _create_idea(c, key, cid, pid, draft_id=r1.json()["draft_id"], confirm=True)
    assert r2.json()["status"] == "complete", r2.json()
    assert "Idea " in r2.json()["reply_text"]
    assert _idea_row(setup["factory"], r1.json()["draft_id"]).type == "idea"


def test_turn_flow_can_reclassify_open_draft(setup):
    c, key, cid, pid = setup["client"], setup["key"], setup["contact_id"], setup["product_id"]
    r1 = _create_idea(c, key, cid, pid)
    draft_id = r1.json()["draft_id"]
    _create_idea(c, key, cid, pid, draft_id=draft_id, type="issue")
    assert _idea_row(setup["factory"], draft_id).type == "issue"


def test_turn_flow_unknown_type_is_422_and_creates_nothing(setup):
    from tests.test_ideation_create_idea import _idea_count

    before = _idea_count(setup["factory"])
    res = _create_idea(
        setup["client"], setup["key"], setup["contact_id"], setup["product_id"], type="complaint"
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "unknown_type"
    assert _idea_count(setup["factory"]) == before


def test_issue_does_not_dedup_against_an_idea(setup):
    """An issue never folds into an existing IDEA with the same wording (and a
    second issue with that wording IS offered the first issue)."""
    c, key, cid, pid = setup["client"], setup["key"], setup["contact_id"], setup["product_id"]
    text = "Let CS export orders to Excel from the list"
    _one_shot(c, key, pid, problem=text)
    r = _create_idea(c, key, cid, pid, message_text=text, type="issue")
    assert r.json()["status"] != "duplicate_candidate", r.json()
    issue = _one_shot(c, key, pid, problem=text, title="Excel issue", type="issue").json()
    r2 = _create_idea(c, key, "+60122222222", pid, message_text=text, type="issue")
    assert r2.json()["status"] == "duplicate_candidate", r2.json()
    assert r2.json()["duplicate_candidate"]["idea_number"] == issue["idea_number"]
    assert "Similar issue exists" in r2.json()["reply_text"]


def test_status_event_payload_carries_idea_type(setup):
    """The CRM's status-update feed tells an issue apart from an idea."""
    c, key, pid = setup["client"], setup["key"], setup["product_id"]
    issue = _one_shot(c, key, pid, type="issue").json()["idea_id"]
    h = _auth(c)
    res = c.post(f"/ideation/ideas/{issue}/status", headers=h, json={"status": "triaged"})
    assert res.status_code == 200, res.text
    from tests.test_ideation_status_events import _events_for

    events = _events_for(setup["factory"], issue)
    assert events
    assert all(e.payload_json["idea_type"] == "issue" for e in events)


# ── read / list ───────────────────────────────────────────────────────────────


def _operator_create(client, h, pid, **extra):
    body = {"productId": pid, "problem": extra.pop("problem", "Something"), **extra}
    return client.post("/ideation/ideas", headers=h, json=body)


def test_operator_create_read_and_list_return_type(setup):
    c, pid = setup["client"], setup["product_id"]
    h = _auth(c)
    a = _operator_create(c, h, pid, problem="Feature A")
    b = _operator_create(c, h, pid, problem="Bug B", type="issue")
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    assert a.json()["type"] == "idea"
    assert b.json()["type"] == "issue"
    got = c.get(f"/ideation/ideas/{b.json()['id']}", headers=h).json()
    assert got["type"] == "issue"
    rows = c.get("/ideation/ideas", headers=h).json()
    assert {r["id"]: r["type"] for r in rows}[a.json()["id"]] == "idea"


def test_operator_create_unknown_type_422(setup):
    c = setup["client"]
    res = _operator_create(c, _auth(c), setup["product_id"], type="nope")
    assert res.status_code == 422, res.text


def test_list_filter_by_type_single_and_multi(setup):
    c, pid = setup["client"], setup["product_id"]
    h = _auth(c)
    a = _operator_create(c, h, pid, problem="Feature A").json()["id"]
    b = _operator_create(c, h, pid, problem="Bug B", type="issue").json()["id"]
    issues = c.get("/ideation/ideas", headers=h, params={"type": "issue"}).json()
    assert [r["id"] for r in issues] == [b]
    ideas = c.get("/ideation/ideas", headers=h, params={"type": "idea"}).json()
    assert [r["id"] for r in ideas] == [a]
    both = c.get("/ideation/ideas", headers=h, params=[("type", "idea"), ("type", "issue")]).json()
    assert {r["id"] for r in both} == {a, b}
    comma = c.get("/ideation/ideas", headers=h, params={"type": "idea,issue"}).json()
    assert {r["id"] for r in comma} == {a, b}
    bad = c.get("/ideation/ideas", headers=h, params={"type": "nope"})
    assert bad.status_code == 422


def test_operator_types_endpoint(setup):
    c = setup["client"]
    res = c.get("/ideation/ideas/types", headers=_auth(c))
    assert res.status_code == 200, res.text
    assert res.json() == [
        {"key": "idea", "label": "Idea", "isDefault": True},
        {"key": "issue", "label": "Issue", "isDefault": False},
    ]


def test_intake_types_endpoint_key_authed(setup):
    c = setup["client"]
    res = c.get("/ideation/intake/idea-types", headers=_key_auth(setup["key"]))
    assert res.status_code == 200, res.text
    assert [t["key"] for t in res.json()] == ["idea", "issue"]
    assert c.get("/ideation/intake/idea-types").status_code == 401


def test_operator_update_can_reclassify(setup):
    c, pid = setup["client"], setup["product_id"]
    h = _auth(c)
    a = _operator_create(c, h, pid, problem="Feature A").json()["id"]
    res = c.patch(f"/ideation/ideas/{a}", headers=h, json={"type": "issue"})
    assert res.status_code == 200, res.text
    assert res.json()["type"] == "issue"
    assert c.patch(f"/ideation/ideas/{a}", headers=h, json={"type": "x"}).status_code == 422


# ── embed (CRM iframe) ────────────────────────────────────────────────────────


def test_embed_create_with_type_and_filter(setup):
    c, factory, pid = setup["client"], setup["factory"], setup["product_id"]
    _seed_connection(factory, product_id=pid)
    h = _bearer(_mint(c))
    a = c.post("/embed/ideas", headers=h, json={"problem": "Feature A"})
    b = c.post("/embed/ideas", headers=h, json={"problem": "Bug B", "type": "issue"})
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    assert a.json()["type"] == "idea" and b.json()["type"] == "issue"
    rows = c.get("/embed/ideas", headers=h, params={"type": "issue"}).json()
    assert [r["id"] for r in rows] == [b.json()["id"]]
    bad = c.post("/embed/ideas", headers=h, json={"problem": "x", "type": "nope"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "unknown_type"


# ── no status / permission change ─────────────────────────────────────────────


def test_issue_rides_the_same_status_lifecycle(setup):
    c, pid = setup["client"], setup["product_id"]
    h = _auth(c)
    b = _operator_create(c, h, pid, problem="Bug B", type="issue").json()
    assert b["status"] == "captured"
    res = c.post(f"/ideation/ideas/{b['id']}/status", headers=h, json={"status": "triaged"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "triaged" and res.json()["type"] == "issue"


@pytest.mark.parametrize("tenant", [DEFAULT_TENANT_ID])
def test_existing_rows_default_to_idea_at_db_level(setup, tenant):
    """A row inserted without ``type`` (as legacy rows were) reads back ``idea``."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import initial_idea_status_id

    db = setup["factory"]()
    try:
        idea = Idea(
            tenant_id=tenant,
            product_id=setup["product_id"],
            status_id=initial_idea_status_id(db, tenant),
            problem="legacy",
        )
        db.add(idea)
        db.commit()
        assert idea.type == "idea"
    finally:
        db.close()

"""Minutes read/edit routes (S4 plan §3.2) - AC-S4-3, AC-S4-8, AC-S4-13.

Mirrors ``test_meetings_stt_router.py``'s ``meetings_client`` fixture + the
own-scope (participant vs ``meetings.manage``) test shape. Every response
field is asserted explicitly (``response_model`` silently drops undeclared
fields).
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import (
    STATUS_READY,
    ActionItem,
    Meeting,
    MeetingParticipant,
    Minutes,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, utc

MEET_URL_PREFIX = "https://meet.google.com/rt"
NOW = utc(2026, 9, 1, 2, 0)
_SEQUENCE = {"n": 0}


@pytest.fixture
def meetings_client(meetings_session_factory):
    def override_get_db():
        session = meetings_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = meetings_session_factory
        yield c
    app.dependency_overrides.clear()


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _meeting(session, *, tenant_id=DEFAULT_TENANT_ID, status=STATUS_READY, title="Weekly product sync"):
    from modules.meetings.services.calendar_sync import dedupe_key

    _SEQUENCE["n"] += 1
    url = f"{MEET_URL_PREFIX}-{_SEQUENCE['n']:04d}"
    meeting = Meeting(
        tenant_id=tenant_id,
        dedupe_key=dedupe_key(url, NOW),
        title=title,
        conference_url=url,
        platform="meet",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status=status,
    )
    session.add(meeting)
    session.flush()
    return meeting


_DEFAULT_SECTIONS = {
    "summary": "We discussed the roadmap.",
    "decisions": ["Ship S4"],
    "action_items": [
        {"text": "Write the deploy note", "owner_email": "alice@example.com", "due_on": "2026-09-10"}
    ],
    "open_questions": ["Who owns S5?"],
    "topic_notes": [{"topic": "Roadmap", "notes": "Q3 focus"}],
}


def _minutes(session, meeting, *, version=1, created_by="llm", sections=None):
    sections = sections or _DEFAULT_SECTIONS
    row = Minutes(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        version=version,
        sections_json=sections,
        created_by=created_by,
        prompt_version_id=None,
        llm_provider="gemini",
        llm_model="gemini-3.5-flash",
    )
    session.add(row)
    session.flush()
    for item in sections["action_items"]:
        session.add(
            ActionItem(
                tenant_id=meeting.tenant_id,
                minutes_id=row.id,
                text=item["text"],
                owner_email=item.get("owner_email"),
                due_on=date(2026, 9, 10) if item.get("due_on") else None,
            )
        )
    session.commit()
    return row


# ── GET latest (AC-S4-8) ──────────────────────────────────────────────────────


def test_get_minutes_returns_every_field_of_the_latest_version(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        _minutes(session, meeting, version=1, created_by="llm")
        minutes_v2 = _minutes(session, meeting, version=2, created_by="llm")
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/minutes", headers=_auth(meetings_client))

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == 2
    assert body["createdBy"] == "llm"
    assert body["llmProvider"] == "gemini"
    assert body["llmModel"] == "gemini-3.5-flash"
    assert body["promptVersion"] is None
    assert body["summary"] == "We discussed the roadmap."
    assert body["decisions"] == ["Ship S4"]
    assert body["openQuestions"] == ["Who owns S5?"]
    assert body["topicNotes"] == [{"topic": "Roadmap", "notes": "Q3 focus"}]
    assert len(body["actionItems"]) == 1
    item = body["actionItems"][0]
    assert item["text"] == "Write the deploy note"
    assert item["ownerEmail"] == "alice@example.com"
    assert item["dueOn"] == "2026-09-10"
    assert item["doneAt"] is None
    assert {v["version"] for v in body["versions"]} == {1, 2}
    assert all(v["createdBy"] == "llm" for v in body["versions"])


def test_get_minutes_404s_when_none_exist_yet(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/minutes", headers=_auth(meetings_client))
    assert res.status_code == 404


def test_get_a_specific_version_by_number(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        _minutes(session, meeting, version=1, sections={**_DEFAULT_SECTIONS, "summary": "v1"})
        _minutes(session, meeting, version=2, sections={**_DEFAULT_SECTIONS, "summary": "v2"})
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(
        f"/meetings/{meeting_id}/minutes/versions/1", headers=_auth(meetings_client)
    )
    assert res.status_code == 200, res.text
    assert res.json()["summary"] == "v1"
    assert res.json()["version"] == 1


def test_an_unknown_version_404s(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        _minutes(session, meeting, version=1)
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(
        f"/meetings/{meeting_id}/minutes/versions/9", headers=_auth(meetings_client)
    )
    assert res.status_code == 404


# ── own scope (mirrors transcripts.py) ───────────────────────────────────────


def _view_only_role(session, name: str):
    from app.models.permission import Permission
    from app.models.role import Role

    role = Role(tenant_id=DEFAULT_TENANT_ID, name=name, description="Meetings only")
    role.permissions = [session.query(Permission).filter(Permission.key == "meetings.view").one()]
    session.add(role)
    session.flush()
    return role


def test_a_non_participant_with_only_view_gets_404(meetings_client):
    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "Bystander")
        bystander = make_admin_user(session, DEFAULT_TENANT_ID, "bystander@example.com")
        bystander.roles = [role]
        meeting = _meeting(session)
        _minutes(session, meeting)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    headers = _auth(meetings_client, email="bystander@example.com", password="demo1234")
    res = meetings_client.get(f"/meetings/{meeting_id}/minutes", headers=headers)
    assert res.status_code == 404


def test_a_participant_can_read_their_own_meetings_minutes(meetings_client):
    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "Attendee")
        attendee = make_admin_user(session, DEFAULT_TENANT_ID, "attendee@example.com")
        attendee.roles = [role]
        meeting = _meeting(session)
        _minutes(session, meeting)
        session.add(
            MeetingParticipant(
                tenant_id=DEFAULT_TENANT_ID,
                meeting_id=meeting.id,
                email=attendee.email,
                user_id=attendee.id,
                is_opted_in=True,
            )
        )
        session.commit()
        meeting_id = meeting.id
    finally:
        session.close()

    headers = _auth(meetings_client, email="attendee@example.com", password="demo1234")
    res = meetings_client.get(f"/meetings/{meeting_id}/minutes", headers=headers)
    assert res.status_code == 200, res.text


def test_unauthenticated_request_is_401(meetings_client):
    res = meetings_client.get("/meetings/does-not-exist/minutes")
    assert res.status_code == 401


# ── PUT: append-only versioning (AC-S4-8) ────────────────────────────────────


def _put_body(**overrides):
    body = {
        "summary": "Edited summary.",
        "decisions": ["Ship S4", "Also ship S5"],
        "actionItems": [
            {"text": "Follow up with legal", "ownerEmail": "bob@example.com", "dueOn": "2026-09-15"},
            {"text": "No owner yet", "ownerEmail": None, "dueOn": None},
        ],
        "openQuestions": [],
        "topicNotes": [{"topic": "Legal", "notes": "Needs review"}],
    }
    body.update(overrides)
    return body


def test_put_creates_the_next_version_and_keeps_the_original(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        _minutes(session, meeting, version=1)
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.put(
        f"/meetings/{meeting_id}/minutes", json=_put_body(), headers=_auth(meetings_client)
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == 2
    assert body["createdBy"] != "llm"  # the editor's own user id
    assert body["summary"] == "Edited summary."
    assert body["decisions"] == ["Ship S4", "Also ship S5"]
    assert len(body["actionItems"]) == 2
    # Two rows created in the same commit tie on ``created_at`` in sqlite -
    # compare as a set, not by position.
    by_text = {i["text"]: i for i in body["actionItems"]}
    assert by_text["Follow up with legal"]["ownerEmail"] == "bob@example.com"
    assert by_text["Follow up with legal"]["dueOn"] == "2026-09-15"
    assert by_text["No owner yet"]["ownerEmail"] is None
    assert by_text["No owner yet"]["dueOn"] is None
    assert {v["version"] for v in body["versions"]} == {1, 2}

    original = meetings_client.get(
        f"/meetings/{meeting_id}/minutes/versions/1", headers=_auth(meetings_client)
    )
    assert original.status_code == 200
    assert original.json()["summary"] == _DEFAULT_SECTIONS["summary"]


def test_put_requires_manage_not_just_view(meetings_client):
    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "ViewOnly")
        viewer = make_admin_user(session, DEFAULT_TENANT_ID, "viewer@example.com")
        viewer.roles = [role]
        meeting = _meeting(session)
        _minutes(session, meeting)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    headers = _auth(meetings_client, email="viewer@example.com", password="demo1234")
    res = meetings_client.put(f"/meetings/{meeting_id}/minutes", json=_put_body(), headers=headers)
    assert res.status_code == 403


# ── toggle (AC-S4-3) ──────────────────────────────────────────────────────────


def test_toggle_sets_then_clears_done_at(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        minutes_row = _minutes(session, meeting)
        item_id = (
            session.query(ActionItem).filter(ActionItem.minutes_id == minutes_row.id).one().id
        )
    finally:
        session.close()

    headers = _auth(meetings_client)
    first = meetings_client.post(f"/meetings/action-items/{item_id}/toggle", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["doneAt"] is not None

    second = meetings_client.post(f"/meetings/action-items/{item_id}/toggle", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["doneAt"] is None


def test_toggle_an_unknown_action_item_404s(meetings_client):
    res = meetings_client.post(
        "/meetings/action-items/does-not-exist/toggle", headers=_auth(meetings_client)
    )
    assert res.status_code == 404


# ── regenerate (AC-S4-13) ────────────────────────────────────────────────────


def test_regenerate_enqueues_a_job(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    res = meetings_client.post(
        f"/meetings/{meeting_id}/minutes/regenerate", headers=_auth(meetings_client)
    )

    assert res.status_code == 202, res.text
    body = res.json()
    assert body["type"] == "meetings.minutes"
    assert body["payload"]["meeting_id"] == meeting_id


def test_regenerate_409s_while_one_is_already_in_flight(meetings_client):
    from app.models.background_job import BackgroundJob
    from app.jobs.service import JobService
    from modules.meetings.jobs import MINUTES

    session = meetings_client._factory()
    try:
        meeting = _meeting(session)
        meeting_id = meeting.id
        session.commit()
        # A job already PENDING for this meeting - never runs (no .enqueue).
        JobService(session).create(
            type=MINUTES, tenant_id=DEFAULT_TENANT_ID, payload={"meeting_id": meeting_id}
        )
    finally:
        session.close()

    res = meetings_client.post(
        f"/meetings/{meeting_id}/minutes/regenerate", headers=_auth(meetings_client)
    )
    assert res.status_code == 409

    session = meetings_client._factory()
    try:
        # The 409 enqueued nothing - still exactly the one pre-seeded job.
        count = (
            session.query(BackgroundJob)
            .filter(BackgroundJob.type == MINUTES, BackgroundJob.tenant_id == DEFAULT_TENANT_ID)
            .count()
        )
        assert count == 1
    finally:
        session.close()


def test_regenerate_requires_manage_not_just_view(meetings_client):
    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "ViewOnly2")
        viewer = make_admin_user(session, DEFAULT_TENANT_ID, "viewer2@example.com")
        viewer.roles = [role]
        meeting = _meeting(session)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    headers = _auth(meetings_client, email="viewer2@example.com", password="demo1234")
    res = meetings_client.post(f"/meetings/{meeting_id}/minutes/regenerate", headers=headers)
    assert res.status_code == 403

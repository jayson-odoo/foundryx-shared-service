"""``GET /meetings/{id}/transcript`` - AC-S3-8.

Everything else about the transcript is exercised in
``test_meetings_stt_jobs.py``; this is only the read shape + the two 404
paths (not transcribed yet, foreign tenant).
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import STATUS_JOINING, STATUS_TRANSCRIBED, Meeting, Transcript, TranscriptSegment
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, utc

MEET_URL = "https://meet.google.com/abc-defg-hij"
NOW = utc(2026, 9, 1, 2, 0)


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


def _meeting(session, *, tenant_id=DEFAULT_TENANT_ID, status=STATUS_JOINING, language=None):
    from modules.meetings.services.calendar_sync import dedupe_key

    meeting = Meeting(
        tenant_id=tenant_id,
        dedupe_key=dedupe_key(MEET_URL, NOW),
        title="Weekly product sync",
        conference_url=MEET_URL,
        platform="meet",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status=status,
        language=language,
    )
    session.add(meeting)
    session.flush()
    return meeting


def _transcribed_meeting(session, *, tenant_id=DEFAULT_TENANT_ID):
    meeting = _meeting(session, tenant_id=tenant_id, status=STATUS_TRANSCRIBED, language="en")
    transcript = Transcript(
        tenant_id=tenant_id, meeting_id=meeting.id, stt_provider="mlx_local", model="whisper-large-v3-turbo"
    )
    session.add(transcript)
    session.flush()
    session.add_all(
        [
            TranscriptSegment(
                tenant_id=tenant_id,
                transcript_id=transcript.id,
                speaker="Alice",
                start_ms=0,
                end_ms=1200,
                text="hello there",
            ),
            TranscriptSegment(
                tenant_id=tenant_id,
                transcript_id=transcript.id,
                speaker=None,
                start_ms=1200,
                end_ms=2400,
                text="how are you",
            ),
        ]
    )
    session.commit()
    return meeting


def test_a_transcribed_meeting_returns_provider_model_language_and_segments(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _transcribed_meeting(session)
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=_auth(meetings_client))

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sttProvider"] == "mlx_local"
    assert body["model"] == "whisper-large-v3-turbo"
    assert body["language"] == "en"
    assert [(s["speaker"], s["startMs"], s["endMs"], s["text"]) for s in body["segments"]] == [
        ("Alice", 0, 1200, "hello there"),
        (None, 1200, 2400, "how are you"),
    ]


def test_a_meeting_that_has_not_been_transcribed_yet_404s(meetings_client):
    session = meetings_client._factory()
    try:
        meeting = _meeting(session, status=STATUS_JOINING)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=_auth(meetings_client))
    assert res.status_code == 404


def test_an_unknown_meeting_id_404s(meetings_client):
    res = meetings_client.get(
        "/meetings/does-not-exist/transcript", headers=_auth(meetings_client)
    )
    assert res.status_code == 404


def test_a_meeting_in_another_tenant_404s(meetings_client):
    from app.services.app_store_service import AppStoreService
    from tests.meetings_helpers import make_tenant

    other_id = "77777777-7777-7777-7777-777777777777"
    session = meetings_client._factory()
    try:
        make_tenant(session, other_id, "Other Co")
        AppStoreService(session).install(other_id, "meetings")
        make_admin_user(session, other_id, "other@example.com")
        meeting = _transcribed_meeting(session, tenant_id=other_id)
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=_auth(meetings_client))
    assert res.status_code == 404


# ── review round: a failed re-run must not serve the stale transcript ────────


def test_a_failed_re_run_404s_even_though_the_old_transcript_row_still_exists(meetings_client):
    """Replace-on-rerun only deletes the OLD ``Transcript`` row on a SUCCESSFUL
    re-run - a re-run that fails leaves that stale row behind while
    ``meeting.status`` flips to ``failed``. Serving it would show a transcript
    for a run that never finished."""
    from modules.meetings.models import STATUS_FAILED

    session = meetings_client._factory()
    try:
        meeting = _transcribed_meeting(session)
        meeting.status = STATUS_FAILED
        meeting.status_reason = "the provider crashed"
        session.commit()
        meeting_id = meeting.id
    finally:
        session.close()

    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=_auth(meetings_client))
    assert res.status_code == 404


# ── review round: reads scope to participants or meetings.manage ────────────


def _view_only_role(session, name: str):
    from app.models.permission import Permission
    from app.models.role import Role

    role = Role(tenant_id=DEFAULT_TENANT_ID, name=name, description="Meetings only")
    role.permissions = [session.query(Permission).filter(Permission.key == "meetings.view").one()]
    session.add(role)
    session.flush()
    return role


def test_a_participant_can_read_their_own_meetings_transcript(meetings_client):
    from modules.meetings.models import MeetingParticipant

    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "Attendee")
        attendee = make_admin_user(session, DEFAULT_TENANT_ID, "attendee@example.com")
        attendee.roles = [role]
        meeting = _transcribed_meeting(session)
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
    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=headers)
    assert res.status_code == 200, res.text


def test_a_non_participant_with_only_meetings_view_404s(meetings_client):
    """``meetings.view`` is "see your OWN meetings" (permissions.csv) - a
    bystander who was never invited must not read someone else's transcript."""
    session = meetings_client._factory()
    try:
        role = _view_only_role(session, "Bystander")
        bystander = make_admin_user(session, DEFAULT_TENANT_ID, "bystander@example.com")
        bystander.roles = [role]
        meeting = _transcribed_meeting(session)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    headers = _auth(meetings_client, email="bystander@example.com", password="demo1234")
    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=headers)
    assert res.status_code == 404


def test_meetings_manage_reads_any_meeting_without_being_a_participant(meetings_client):
    from app.models.permission import Permission
    from app.models.role import Role

    session = meetings_client._factory()
    try:
        role = Role(tenant_id=DEFAULT_TENANT_ID, name="Ops", description="Manage meetings")
        role.permissions = list(
            session.query(Permission)
            .filter(Permission.key.in_(["meetings.view", "meetings.manage"]))
            .all()
        )
        session.add(role)
        session.flush()
        ops = make_admin_user(session, DEFAULT_TENANT_ID, "ops@example.com")
        ops.roles = [role]
        meeting = _transcribed_meeting(session)
        meeting_id = meeting.id
        session.commit()
    finally:
        session.close()

    headers = _auth(meetings_client, email="ops@example.com", password="demo1234")
    res = meetings_client.get(f"/meetings/{meeting_id}/transcript", headers=headers)
    assert res.status_code == 200, res.text

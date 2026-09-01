"""``services/minutes.py`` - ``resolve_llm`` + ``generate_minutes`` (S4 plan
§3.1). AC-S4-2, AC-S4-3, AC-S4-4, AC-S4-5, AC-S4-6, AC-S4-7, AC-S4-9.

The LLM adapter is mocked at the seam (``get_provider``, imported into
``services.minutes``'s own namespace) - this suite never calls a real
provider.
"""
import json
from datetime import date, timedelta

import pytest
from cryptography.fernet import InvalidToken

from app.integrations.base import LLMError, LLMResult
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.integration_activity import IntegrationActivity, SOURCE_MEETINGS
from app.secrets import encrypt_secret
from modules.meetings.models import (
    STATUS_JOINING,
    STATUS_READY,
    STATUS_TRANSCRIBED,
    ActionItem,
    Meeting,
    MeetingParticipant,
    Minutes,
    Transcript,
    TranscriptSegment,
)
from modules.meetings.services import minutes as minutes_module
from modules.meetings.services.minutes import (
    MinutesGenerationError,
    MinutesResolutionError,
    generate_minutes,
    resolve_llm,
)
from modules.meetings.services.settings import MeetingsSettingsService
from tests.meetings_helpers import utc

NOW = utc(2026, 9, 1, 2, 0)
_SEQUENCE = {"n": 0}


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


class _FakeLLMProvider:
    """A scripted ``IntegrationProvider`` of ``type='llm'`` - the ``.complete``
    call shape every real adapter (gemini/anthropic/openai) shares."""

    type = "llm"

    def __init__(self, *, texts=None, error=None):
        self.texts = list(texts or [])
        self.error = error
        self.calls = []

    def complete(
        self, config, credentials, *, model, system, messages, output_schema=None, temperature=0
    ):
        self.calls.append(
            {
                "config": config,
                "credentials": credentials,
                "model": model,
                "system": system,
                "messages": messages,
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        return LLMResult(text=self.texts.pop(0))


def _patch_provider(monkeypatch, provider, *, expect_name="gemini"):
    def _get(name):
        return provider if name == expect_name else None

    monkeypatch.setattr(minutes_module, "get_provider", _get)


def _valid_json(*, summary="Summary text", action_items=None):
    payload = {
        "summary": summary,
        "decisions": ["Decided X"],
        "action_items": (
            action_items
            if action_items is not None
            else [{"text": "Send the deck", "owner_email": "alice@example.com", "due_on": "2026-09-10"}]
        ),
        "open_questions": ["What about Y?"],
        "topic_notes": [{"topic": "Budget", "notes": "Discussed budget"}],
    }
    return json.dumps(payload)


def _meeting(db, *, tenant_id=DEFAULT_TENANT_ID, title="Weekly sync", status=STATUS_TRANSCRIBED):
    from modules.meetings.services.calendar_sync import dedupe_key

    _SEQUENCE["n"] += 1
    url = f"https://meet.google.com/svc-{_SEQUENCE['n']:04d}"
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
    db.add(meeting)
    db.flush()
    return meeting


def _transcript(db, meeting, *, segments=None):
    transcript = Transcript(
        tenant_id=meeting.tenant_id, meeting_id=meeting.id, stt_provider="mlx_local", model="whisper"
    )
    db.add(transcript)
    db.flush()
    for seg in segments or [
        {"speaker": "Alice", "start_ms": 0, "end_ms": 2000, "text": "Let's start", "language": "en"},
        {"speaker": "Bob", "start_ms": 2000, "end_ms": 5000, "text": "Sounds good", "language": "en"},
    ]:
        db.add(TranscriptSegment(tenant_id=meeting.tenant_id, transcript_id=transcript.id, **seg))
    db.commit()
    return transcript


def _participant(db, meeting, *, email="alice@example.com", display_name="Alice"):
    row = MeetingParticipant(
        tenant_id=meeting.tenant_id, meeting_id=meeting.id, email=email, display_name=display_name
    )
    db.add(row)
    db.commit()
    return row


def _connection(db, *, provider="anthropic", model=None, is_active=True, api_key="test-key"):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider=provider,
        type="llm",
        name=f"{provider} minutes",
        config_json={"model": model} if model else {},
        credentials_json=encrypt_secret({"apiKey": api_key}),
        is_active=is_active,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _activity_rows(db, meeting_id):
    return (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.source == SOURCE_MEETINGS,
            IntegrationActivity.operation == "minutes_generate",
            IntegrationActivity.external_ref == meeting_id,
        )
        .order_by(IntegrationActivity.created_at.asc(), IntegrationActivity.id.asc())
        .all()
    )


# ── generate_minutes: happy path (AC-S4-2, AC-S4-3, AC-S4-6) ────────────────


def test_a_successful_run_writes_one_minutes_row_and_its_action_items(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    _participant(db, meeting)
    provider = _FakeLLMProvider(texts=[_valid_json()])
    _patch_provider(monkeypatch, provider)

    minutes_row = generate_minutes(db, meeting)

    assert minutes_row.version == 1
    assert minutes_row.created_by == "llm"
    assert minutes_row.llm_provider == "gemini"
    assert minutes_row.llm_model == "gemini-3.5-flash"
    sections = minutes_row.sections_json
    assert set(sections.keys()) == {
        "summary",
        "decisions",
        "action_items",
        "open_questions",
        "topic_notes",
    }

    db.refresh(meeting)
    assert meeting.status == STATUS_READY

    items = db.query(ActionItem).filter(ActionItem.minutes_id == minutes_row.id).all()
    assert len(items) == 1
    assert items[0].text == "Send the deck"
    assert items[0].owner_email == "alice@example.com"
    assert items[0].due_on == date(2026, 9, 10)

    rows = _activity_rows(db, meeting.id)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].latency_ms is not None


def test_an_invalid_due_on_is_stored_as_null_never_guessed(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(
        texts=[
            _valid_json(
                action_items=[{"text": "Follow up", "owner_email": None, "due_on": "next Tuesday"}]
            )
        ]
    )
    _patch_provider(monkeypatch, provider)

    minutes_row = generate_minutes(db, meeting)

    item = db.query(ActionItem).filter(ActionItem.minutes_id == minutes_row.id).one()
    assert item.due_on is None
    assert item.owner_email is None


# ── language variable reaches the rendered prompt (AC-S4-4) ─────────────────


def test_the_tenant_minutes_language_reaches_the_rendered_prompt(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    MeetingsSettingsService(db).update(DEFAULT_TENANT_ID, {"minutesLanguage": "zh"})
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(texts=[_valid_json()])
    _patch_provider(monkeypatch, provider)

    generate_minutes(db, meeting)

    assert len(provider.calls) == 1
    prompt_text = provider.calls[0]["messages"][0]["content"]
    assert "Write the minutes in zh." in prompt_text
    assert "{{language}}" not in prompt_text
    assert "{{transcript}}" not in prompt_text


# ── LLM resolution order: connection > platform env > typed failure ─────────


def test_resolve_llm_uses_the_tenant_connection_when_set(db):
    connection = _connection(db, provider="anthropic", model="claude-haiku-4-5")
    MeetingsSettingsService(db).update(DEFAULT_TENANT_ID, {"llmConnectionId": connection.id})

    resolved = resolve_llm(db, DEFAULT_TENANT_ID)

    assert resolved.provider_name == "anthropic"
    assert resolved.model == "claude-haiku-4-5"
    assert resolved.credentials == {"apiKey": "test-key"}


def test_resolve_llm_falls_back_to_the_platform_default_when_unset(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    monkeypatch.setattr(settings, "meetings_llm_provider", "gemini")
    monkeypatch.setattr(settings, "meetings_llm_model", "gemini-3.5-flash")

    resolved = resolve_llm(db, DEFAULT_TENANT_ID)

    assert resolved.provider_name == "gemini"
    assert resolved.model == "gemini-3.5-flash"
    assert resolved.credentials == {"apiKey": "platform-key"}


def test_resolve_llm_fails_loudly_when_neither_is_usable(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "")

    with pytest.raises(MinutesResolutionError):
        resolve_llm(db, DEFAULT_TENANT_ID)


def test_resolve_llm_fails_on_an_inactive_connection_rather_than_falling_back(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    connection = _connection(db, is_active=False)
    MeetingsSettingsService(db).update(DEFAULT_TENANT_ID, {"llmConnectionId": connection.id})

    with pytest.raises(MinutesResolutionError):
        resolve_llm(db, DEFAULT_TENANT_ID)


def test_an_undecryptable_connection_stamps_it_error_and_fails(db, monkeypatch):
    connection = _connection(db)
    MeetingsSettingsService(db).update(DEFAULT_TENANT_ID, {"llmConnectionId": connection.id})

    def _boom(_raw):
        raise InvalidToken()

    monkeypatch.setattr(minutes_module, "decrypt_secret", _boom)

    with pytest.raises(MinutesResolutionError):
        resolve_llm(db, DEFAULT_TENANT_ID)

    db.refresh(connection)
    assert connection.status == "ERROR"
    assert connection.last_error


# ── structured-output discipline: retry once, then fail (AC-S4-7) ───────────


def test_a_malformed_response_gets_one_corrective_retry_then_succeeds(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(texts=["not json at all", _valid_json()])
    _patch_provider(monkeypatch, provider)

    minutes_row = generate_minutes(db, meeting)

    assert len(provider.calls) == 2
    # The retry prompt carries the validation error forward.
    assert "rejected" in provider.calls[1]["messages"][0]["content"]
    rows = _activity_rows(db, meeting.id)
    # Two separate activity rows, one per attempt (AC-S4-6) - order is not
    # asserted, sqlite's ``created_at`` resolution is too coarse to trust it.
    assert sorted(r.status for r in rows) == ["error", "success"]
    db.refresh(meeting)
    assert meeting.status == STATUS_READY
    assert db.query(Minutes).filter(Minutes.meeting_id == meeting.id).count() == 1


def test_two_malformed_responses_fail_the_run_with_no_partial_row(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(texts=["nope", "still not json"])
    _patch_provider(monkeypatch, provider)

    with pytest.raises(MinutesGenerationError):
        generate_minutes(db, meeting)

    assert len(provider.calls) == 2
    rows = _activity_rows(db, meeting.id)
    assert [r.status for r in rows] == ["error", "error"]
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED  # untouched
    assert db.query(Minutes).filter(Minutes.meeting_id == meeting.id).count() == 0
    assert db.query(ActionItem).count() == 0


def test_a_missing_section_is_also_a_shape_failure(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    incomplete = json.dumps({"summary": "x", "decisions": []})
    provider = _FakeLLMProvider(texts=[incomplete, incomplete])
    _patch_provider(monkeypatch, provider)

    with pytest.raises(MinutesGenerationError):
        generate_minutes(db, meeting)

    assert len(provider.calls) == 2


def test_a_transport_failure_never_retries(db, monkeypatch):
    """A bad key / network error is not "the shape was wrong" - no
    corrective retry, one clean failure."""
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(error=LLMError("The API key was rejected by the provider."))
    _patch_provider(monkeypatch, provider)

    with pytest.raises(MinutesGenerationError):
        generate_minutes(db, meeting)

    assert len(provider.calls) == 1
    rows = _activity_rows(db, meeting.id)
    assert len(rows) == 1
    assert rows[0].status == "error"
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED


def test_a_meeting_with_no_transcript_fails_loudly(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db, status=STATUS_JOINING)

    with pytest.raises(minutes_module.MinutesError):
        generate_minutes(db, meeting)


# ── append-only versioning: a re-run appends, never overwrites (AC-S4-8/9) ──


def test_a_rerun_appends_the_next_version_and_keeps_the_first(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    _patch_provider(monkeypatch, _FakeLLMProvider(texts=[_valid_json(summary="First pass")]))
    first = generate_minutes(db, meeting)
    assert first.version == 1

    db.refresh(meeting)
    meeting.status = STATUS_TRANSCRIBED  # a real re-run only happens on a transcribed meeting
    db.commit()

    _patch_provider(monkeypatch, _FakeLLMProvider(texts=[_valid_json(summary="Second pass")]))
    second = generate_minutes(db, meeting)
    assert second.version == 2
    assert second.sections_json["summary"] == "Second pass"

    first_still_there = db.query(Minutes).filter(Minutes.id == first.id).one()
    assert first_still_there.sections_json["summary"] == "First pass"
    assert db.query(Minutes).filter(Minutes.meeting_id == meeting.id).count() == 2


# ── empty prompt registry still succeeds (AC-S4-9) ───────────────────────────


def test_the_job_succeeds_against_the_hardcoded_fallback_with_an_empty_registry(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    provider = _FakeLLMProvider(texts=[_valid_json()])
    _patch_provider(monkeypatch, provider)

    minutes_row = generate_minutes(db, meeting)

    assert minutes_row.prompt_version_id is None  # no seeded row - fallback used
    assert len(provider.calls) == 1


# ── the ``meetings.minutes`` job handler (jobs.py, AC-S4-1/12) ──────────────


def _minutes_job(db, meeting):
    from app.jobs.service import JobService
    from modules.meetings.jobs import MINUTES

    return JobService(db).create(
        type=MINUTES, tenant_id=meeting.tenant_id, payload={"meeting_id": meeting.id}
    )


def _run_job(db, job_id):
    from app.jobs.service import run_job

    return run_job(db, job_id)


def test_run_minutes_reports_a_result_shaped_for_the_job_log(db, monkeypatch):
    from app.models.background_job import JOB_DONE

    from app.config import settings

    monkeypatch.setattr(settings, "meetings_llm_api_key", "platform-key")
    meeting = _meeting(db)
    _transcript(db, meeting)
    _patch_provider(monkeypatch, _FakeLLMProvider(texts=[_valid_json()]))

    finished = _run_job(db, _minutes_job(db, meeting).id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {
        "minutesVersion": 1,
        "actionItems": 1,
        "llmProvider": "gemini",
        "llmModel": "gemini-3.5-flash",
        "latencyMs": finished.result_json["latencyMs"],
    }
    assert finished.result_json["latencyMs"] >= 0


def test_run_minutes_fails_the_job_and_leaves_the_meeting_transcribed_on_a_typed_error(
    db, monkeypatch
):
    from app.config import settings
    from app.models.background_job import JOB_FAILED

    monkeypatch.setattr(settings, "meetings_llm_api_key", "")  # neither resolves (AC-S4-5)
    meeting = _meeting(db)
    _transcript(db, meeting)

    finished = _run_job(db, _minutes_job(db, meeting).id)

    assert finished.status == JOB_FAILED
    assert finished.error
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED  # never crashed the worker


def test_run_minutes_missing_meeting_id_fails_loudly(db):
    from app.jobs.service import JobService, run_job
    from app.models.background_job import JOB_FAILED
    from modules.meetings.jobs import MINUTES

    job = JobService(db).create(type=MINUTES, tenant_id=DEFAULT_TENANT_ID, payload={})

    finished = run_job(db, job.id)

    assert finished.status == JOB_FAILED
    assert "meeting_id" in (finished.error or "")


def test_run_minutes_a_meeting_id_that_no_longer_exists_is_a_clean_skip(db):
    from app.jobs.service import JobService, run_job
    from app.models.background_job import JOB_DONE
    from modules.meetings.jobs import MINUTES

    job = JobService(db).create(
        type=MINUTES, tenant_id=DEFAULT_TENANT_ID, payload={"meeting_id": "does-not-exist"}
    )

    finished = run_job(db, job.id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {"skipped": "meeting is gone"}

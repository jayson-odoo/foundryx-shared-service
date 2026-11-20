"""Plan 44 review round - pins: a malformed row at each existing site stores
no value from the row, in the job's failures or in the stored failures file.
Placeholder data only; every value that must not appear in output carries ``MARKER-``."""
import json

import httpx

from app.models import DEFAULT_TENANT_ID

from tests.test_omnichannel_migration_unreadable_rows import (
    _assert_no_markers,
    _sample,
    bad_contact,
)
from tests.test_omnichannel_respondio_migration_jobs import (
    _default_workspace,
    _make_connection,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import (
    _make_channel,
    _make_full_job,
    _pages_handler_full,
)


def _everything(db, job):
    from modules.omnichannel.services.migration_service import MigrationService

    return json.dumps(
        [job.result_json, job.cursor_json, job.logs_json, job.error,
         MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id)],
        default=str,
    )


def _run(db, handler, monkeypatch, *, channel_map=None):
    from modules.omnichannel.services.migration_service import run_migration_job

    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    _stub_client(monkeypatch, handler)
    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=channel_map
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    return job


def test_ac_44_11_a_malformed_channel_row_in_the_identities_phase_stores_no_value(session_factory, monkeypatch):
    db = session_factory()
    contact = {"id": 930001, "firstName": "Good", "phone": "+15550930001"}
    bad_channel_row = {"id": 1, "name": "MARKER-NAME", "meta": {"phone": "MARKER-PHONE"}}
    inner = _pages_handler_full(
        {None: ([contact], None)}, channels_by_contact={"id:930001": [bad_channel_row]}
    )
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:930001/channels"):
            reached.append(1)
        return inner(request)

    job = _run(db, handler, monkeypatch)

    assert reached, "the channels stub was never reached"
    rows = [r for r in _sample(job) if r["entity"] == "identities"]
    assert len(rows) == 1, _sample(job)
    assert rows[0]["reason"].startswith("malformed channel payload: could not read: "), rows[0]
    _assert_no_markers(_everything(db, job))
    db.close()


def test_ac_44_11_a_malformed_message_row_stores_no_value(session_factory, monkeypatch):
    db = session_factory()
    contact = {"id": 930002, "firstName": "Good", "phone": "+15550930002"}
    bad_message_row = {"messageId": "MARKER-MSG", "traffic": "incoming", "message": {"type": "text", "text": "MARKER-TEXT"}}
    inner = _pages_handler_full(
        {None: ([contact], None)},
        messages_by_contact={"id:930002": {None: ([bad_message_row], None)}},
    )
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/message/list"):
            reached.append(1)
        return inner(request)

    job = _run(db, handler, monkeypatch)

    assert reached, "the message stub was never reached"
    rows = [r for r in _sample(job) if r["entity"] == "messages"]
    assert len(rows) == 1, _sample(job)
    assert rows[0]["reason"].startswith("malformed message payload: could not read: "), rows[0]
    _assert_no_markers(_everything(db, job))
    db.close()


def test_ac_44_11_a_malformed_contact_row_in_the_walk_stores_no_value(session_factory, monkeypatch):
    db = session_factory()
    inner = _pages_handler_full({None: ([bad_contact(7321)], None)})
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/list"):
            reached.append(1)
        return inner(request)

    job = _run(db, handler, monkeypatch)

    assert reached, "the contact list stub was never reached"
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1 and rows[0]["reason"].startswith("malformed contact payload: could not read: "), rows
    _assert_no_markers(_everything(db, job))
    db.close()


def test_ac_44_11_an_event_refetch_that_fails_the_model_stores_no_value(session_factory, monkeypatch):
    db = session_factory()
    good = {"id": 930003, "firstName": "Good", "phone": "+15550930003"}
    refetch_bad = {"id": 930003, "firstName": "MARKER-FIRST", "email": "marker@example.com", "tags": "MARKER-TAGS"}
    inner = _pages_handler_full({None: ([good], None)})
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:930003"):
            reached.append(1)
            return httpx.Response(200, json=refetch_bad)
        return inner(request)

    job = _run(db, handler, monkeypatch)

    assert reached, "the re-fetch stub was never reached"
    rows = [r for r in _sample(job) if r["entity"] == "events"]
    assert len(rows) == 1 and "tags" in rows[0]["reason"], _sample(job)
    _assert_no_markers(_everything(db, job))
    db.close()

"""Plan 44 review round - red tests. Placeholder data only; a value that must
not leak carries ``MARKER-``."""
import json
import re

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DEFAULT_TENANT_ID

from tests.test_omnichannel_migration_unreadable_rows import (
    GOOD_CHANNEL,
    GOOD_CONTACT,
    _assert_no_markers,
    _channel_map_error,
    _full_handler,
    _handler,
    _patch_client_factory,
    _post_job,
    _preflight,
    _sample,
    _setup,
    _state,
    bad_channel,
    bad_contact,
    soft_client,  # noqa: F401 - fixture
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
from tests.test_omnichannel_respondio_migration_s5 import _make_csv_job, _upload_key, _csv_bytes

DB_ERROR_TEXT = "INSERT INTO t (name) VALUES (%(name)s)"


def _db_error():
    return IntegrityError(DB_ERROR_TEXT, {"name": "MARKER-DB"}, Exception("x"))


def _everything(db, job):
    from modules.omnichannel.services.migration_service import MigrationService

    return json.dumps(
        [job.result_json, job.cursor_json, job.logs_json, job.error,
         MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id)],
        default=str,
    )


# ── B. a stored reason never holds a writer error's text ────────────────────


def test_ac_44_11_csv_contact_write_error_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job
    from modules.omnichannel.services.migration_writer import MigrationWriter

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _csv_bytes(["First Name", "Phone"], [["Csv", "+15550000002"]]))
    reached = []

    def failing(self, source):
        reached.append(1)
        raise _db_error()

    monkeypatch.setattr(MigrationWriter, "write_contact", failing)
    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the writer stub was never reached"
    assert job.status == "done", job.error
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1, _sample(job)
    _assert_no_markers(_everything(db, job))
    assert "INSERT" not in _everything(db, job)
    assert "IntegrityError" in rows[0]["reason"], rows[0]
    db.close()


def test_ac_44_11_message_write_error_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job
    from modules.omnichannel.services.migration_writer import MigrationWriter

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()
    contact = {"id": 940001, "firstName": "Good", "phone": "+15551234568"}
    handler = _pages_handler_full(
        {None: ([contact], None)},
        channels_by_contact={"id:940001": [{"id": 601, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15551234568"}}]},
        messages_by_contact={"id:940001": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 601, "message": {"type": "text", "text": "hello"}},
        ], None)}},
    )
    _stub_client(monkeypatch, handler)
    reached = []

    def failing(self, *args, **kwargs):
        reached.append(1)
        raise _db_error()

    monkeypatch.setattr(MigrationWriter, "write_message", failing)
    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "601", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the writer stub was never reached"
    assert job.status == "done", job.error
    rows = [r for r in _sample(job) if r["entity"] == "messages"]
    assert len(rows) == 1, _sample(job)
    _assert_no_markers(_everything(db, job))
    assert "INSERT" not in _everything(db, job)
    assert "IntegrityError" in rows[0]["reason"], rows[0]
    db.close()


def test_ac_44_11_contact_write_error_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job
    from modules.omnichannel.services.migration_writer import MigrationWriter

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    _stub_client(monkeypatch, _pages_handler_full({None: ([dict(GOOD_CONTACT)], None)}))
    reached = []

    def failing(self, source):
        reached.append(1)
        raise _db_error()

    monkeypatch.setattr(MigrationWriter, "write_contact", failing)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the writer stub was never reached"
    assert job.status == "done", job.error
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1, _sample(job)
    _assert_no_markers(_everything(db, job))
    assert "INSERT" not in _everything(db, job)
    assert "IntegrityError" in rows[0]["reason"], rows[0]
    db.close()


# ── C. the channel read happens before the in-progress lookup ───────────────


def test_ac_44_20_the_channel_read_comes_before_the_in_progress_lookup(soft_client, monkeypatch):
    from modules.omnichannel.respondio.client import RespondIoClient
    from modules.omnichannel.services.migration_service import MigrationService

    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    events = []
    real_lookup = MigrationService._in_progress_job
    real_list = RespondIoClient.list_space_channels

    def lookup_spy(self, *args, **kwargs):
        events.append("lookup")
        return real_lookup(self, *args, **kwargs)

    def list_spy(self):
        events.append("channels")
        return real_list(self)

    monkeypatch.setattr(MigrationService, "_in_progress_job", lookup_spy)
    monkeypatch.setattr(RespondIoClient, "list_space_channels", list_spy)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 201, res.text
    assert "lookup" in events and "channels" in events, events
    assert events.index("channels") < events.index("lookup"), events


# ── D. an odd answer from the source is a 422 / 200, never a 500 ────────────

SOURCE_ERROR = "Could not read the source channels from respond.io. Try again."


def _odd_source(state, kind):
    base = _handler(state)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/channel") and state.get("odd"):
            state["odd_reached"] = state.get("odd_reached", 0) + 1
            if kind == "not_json":
                return httpx.Response(200, content=b"<html>MARKER-BODY</html>")
            if kind == "items_int":
                return httpx.Response(200, json={"items": 5, "pagination": {"next": None}})
            if kind == "items_dict":
                return httpx.Response(200, json={"items": {"a": 1}, "pagination": {"next": None}})
            if kind == "invalid_url":
                raise httpx.InvalidURL("MARKER-URL")
        return base(request)

    return handler


def _odd_setup(soft_client, monkeypatch, kind):
    state = _state()
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    _patch_client_factory(monkeypatch, _odd_source(state, kind))
    return state, h, connection_id, ws_id


@pytest.mark.parametrize("kind", ["not_json", "items_int", "items_dict", "invalid_url"])
def test_ac_44_20_an_odd_source_answer_during_the_run_check_is_a_422_on_channel_map(
    soft_client, monkeypatch, kind
):
    state, h, connection_id, ws_id = _odd_setup(soft_client, monkeypatch, kind)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    state["odd"] = True

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert state.get("odd_reached"), "the odd answer was never served"
    assert res.status_code == 422, (res.status_code, res.text)
    assert "channelMap" in res.json()["detail"]["fieldErrors"], res.text
    _assert_no_markers(res.text)


@pytest.mark.parametrize("kind", ["not_json", "items_int", "invalid_url"])
def test_ac_44_01_an_odd_source_answer_does_not_fail_preflight(soft_client, monkeypatch, kind):
    state, h, connection_id, ws_id = _odd_setup(soft_client, monkeypatch, kind)
    state["odd"] = True

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert state.get("odd_reached"), "the odd answer was never served"
    assert res.status_code == 200, (res.status_code, res.text)
    _assert_no_markers(res.text)


# ── F. a job resumed after the last contacts page counts once ───────────────


def test_ac_44_10_a_job_that_crashed_after_the_last_contacts_page_counts_one_walk(session_factory, monkeypatch):
    from app.models.background_job import JOB_RUNNING
    from app.jobs.service import JobService
    from modules.omnichannel.services.migration_service import run_migration_job

    class Crash(BaseException):
        """A process kill: passes through every `except Exception`."""

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    handler = _full_handler({None: ([dict(GOOD_CONTACT), bad_contact(7321)], None)})
    _stub_client(monkeypatch, handler)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")

    real_set_cursor = JobService.set_cursor
    state = {"crash": True, "reached": 0}

    def set_cursor(self, job_, cursor, *args, **kwargs):
        if state["crash"] and (cursor or {}).get("phase") == "identities":
            state["reached"] += 1
            raise Crash()
        return real_set_cursor(self, job_, cursor, *args, **kwargs)

    monkeypatch.setattr(JobService, "set_cursor", set_cursor)
    with pytest.raises(Crash):
        run_migration_job(db, job)
    assert state["reached"] == 1, "the crash point was never reached"
    state["crash"] = False
    db.rollback()
    db.refresh(job)
    assert (job.cursor_json or {}).get("phase") == "contacts", job.cursor_json

    job.status = JOB_RUNNING
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    contacts = job.result_json["report"]["entities"]["contacts"]
    assert contacts["fetched"] == 2, contacts
    blockers = job.result_json["report"]["blockers"]
    assert "1 source contact(s) could not be read and were skipped." in blockers, blockers
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1, rows


# ── G. the closing sentence only when Skip can help ─────────────────────────


def test_ac_44_22_only_channels_with_no_id_block_so_the_message_does_not_say_mark_each_one(
    soft_client, monkeypatch
):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201

    message = _channel_map_error(_post_job(soft_client, h, connection_id, ws_id, mode="run"))

    assert "A channel with no readable id cannot be marked Skip." in message, message
    assert "Mark each one Skip" not in message, message


def test_ac_44_22_a_mix_of_channels_with_and_without_an_id_still_says_mark_each_one(
    soft_client, monkeypatch
):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011), no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201

    message = _channel_map_error(_post_job(soft_client, h, connection_id, ws_id, mode="run"))

    assert "7011" in message and "cannot be marked Skip" in message, message
    assert "Mark each one Skip" in message, message

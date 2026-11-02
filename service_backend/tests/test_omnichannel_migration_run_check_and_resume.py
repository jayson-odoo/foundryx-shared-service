"""Plan 44 review round - red tests. Placeholder data only; a value that must
not appear in output carries ``MARKER-``."""
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


# ── resume lists a row once in the CSV phases ───────────────────────────────


class _Crash(BaseException):
    """A process kill: passes through every `except Exception`."""


def _rows_of(job, entity):
    return [r for r in _sample(job) if r["entity"] == entity]


def _resume(db, job):
    from app.models.background_job import JOB_RUNNING
    from modules.omnichannel.services.migration_service import run_migration_job

    db.rollback()
    db.refresh(job)
    job.status = JOB_RUNNING
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)


def test_ac_44_10_a_csv_contacts_resume_lists_a_row_once(session_factory, monkeypatch):
    from app.jobs.service import JobService
    from modules.omnichannel.services.migration_service import run_migration_job
    from modules.omnichannel.services.migration_writer import MigrationWriter

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _csv_bytes(["First Name", "Phone"], [["Csv", "+15550000012"]]))
    writer_calls = []

    def failing(self, source):
        writer_calls.append(1)
        raise RuntimeError("x")

    monkeypatch.setattr(MigrationWriter, "write_contact", failing)
    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    real = JobService.set_cursor
    state = {"crash": True, "reached": 0}

    def set_cursor(self, job_, cursor, *args, **kwargs):
        if state["crash"] and (cursor or {}).get("phase") == "quick_replies":
            state["reached"] += 1
            raise _Crash()
        return real(self, job_, cursor, *args, **kwargs)

    monkeypatch.setattr(JobService, "set_cursor", set_cursor)
    with pytest.raises(_Crash):
        run_migration_job(db, job)
    assert state["reached"] == 1, "the crash point was never reached"
    state["crash"] = False
    _resume(db, job)

    assert job.status == "done", job.error
    assert len(writer_calls) >= 1
    assert len(_rows_of(job, "contacts")) == 1, _rows_of(job, "contacts")
    db.close()


def test_ac_44_10_a_quick_replies_resume_lists_a_row_once(session_factory, monkeypatch):
    from app.jobs.service import JobService
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _csv_bytes(["First Name", "Phone"], [["Csv", "+15550000013"]]))
    skey = _upload_key(db, DEFAULT_TENANT_ID, "snippets", _csv_bytes(["shortcut", "body"], [["hi", ""]]))
    job = _make_csv_job(
        db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, snippets_csv_key=skey, mode="run"
    )
    real = JobService.finish
    state = {"crash": True, "reached": 0}

    def finish(self, job_, *args, **kwargs):
        if state["crash"]:
            state["reached"] += 1
            raise _Crash()
        return real(self, job_, *args, **kwargs)

    monkeypatch.setattr(JobService, "finish", finish)
    with pytest.raises(_Crash):
        run_migration_job(db, job)
    assert state["reached"] == 1, "the crash point was never reached"
    state["crash"] = False
    _resume(db, job)

    assert job.status == "done", job.error
    rows = _rows_of(job, "quickReplies")
    assert len(rows) == 1, rows
    db.close()


# ── a storage failure stores fixed text ─────────────────────────────────────

STORAGE_ERROR = "storage key conn:MARKER-CONN:MARKER-KEY could not be read"


def _failing_storage(monkeypatch, reached):
    from modules.omnichannel.services import migration_service

    real_factory = migration_service.storage_for_tenant

    class Wrap:
        def __init__(self, real):
            self._real = real

        def fetch(self, key):
            if "MARKER" in key:
                reached.append(key)
                raise RuntimeError(STORAGE_ERROR)
            return self._real.fetch(key)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(
        migration_service, "storage_for_tenant", lambda db, tenant_id: Wrap(real_factory(db, tenant_id))
    )


@pytest.mark.parametrize("which", ["contacts", "snippets"])
def test_ac_44_11_a_storage_fetch_failure_stores_fixed_text(session_factory, monkeypatch, which):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()
    marked_key = "conn:MARKER-CONN:MARKER-KEY"
    good = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _csv_bytes(["First Name", "Phone"], [["Csv", "+15550000014"]]))
    reached = []
    _failing_storage(monkeypatch, reached)
    if which == "contacts":
        job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=marked_key, mode="run")
        entity = "contacts"
    else:
        job = _make_csv_job(
            db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=good, snippets_csv_key=marked_key, mode="run"
        )
        entity = "quickReplies"

    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the storage stub was never reached"
    assert job.status == "done", job.error
    rows = _rows_of(job, entity)
    assert len(rows) == 1, _sample(job)
    _assert_no_markers(_everything(db, job))
    db.close()


# ── the timestamp step stores no error text ─────────────────────────────────


def test_ac_44_11_a_timestamp_step_failure_stores_no_error_text(session_factory, monkeypatch):
    from modules.omnichannel.services import migration_service
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()
    contact = {"id": 940002, "firstName": "Good", "phone": "+15551234569"}
    handler = _pages_handler_full(
        {None: ([contact], None)},
        channels_by_contact={"id:940002": [{"id": 601, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15551234569"}}]},
        messages_by_contact={"id:940002": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 601, "message": {"type": "text", "text": "hello"}},
        ], None)}},
    )
    _stub_client(monkeypatch, handler)
    reached = []

    def failing(*args, **kwargs):
        reached.append(1)
        raise RuntimeError("timestamps broke for MARKER-TS")

    monkeypatch.setattr(migration_service, "resolve_message_timestamps", failing)
    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "601", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the timestamp stub was never reached"
    assert job.status == "done", job.error
    assert len(_rows_of(job, "messages")) == 1, _sample(job)
    _assert_no_markers(_everything(db, job))
    db.close()


# ── a vendor message is capped, and only a string is kept ───────────────────

LONG = "A" * 5000


def _count_a(text):
    return text.count("A")


def _error_handler(body):
    inner = _pages_handler_full({None: ([dict(GOOD_CONTACT)], None)})
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/list"):
            reached.append(1)
            return httpx.Response(404, json=body)
        return inner(request)

    handler.reached = reached
    return handler


def test_ac_44_11_a_long_vendor_message_is_capped_in_the_error_and_the_logs(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    handler = _error_handler({"code": "x", "message": LONG})
    _stub_client(monkeypatch, handler)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")

    run_migration_job(db, job)
    db.refresh(job)

    assert handler.reached, "the contact list stub was never reached"
    assert job.status == "failed", job.status
    assert _count_a(job.error or "") <= 300, len(job.error or "")
    assert _count_a(json.dumps(job.logs_json, default=str)) <= 300
    db.close()


def test_ac_44_11_a_long_vendor_message_is_capped_in_a_stored_reason(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    inner = _pages_handler_full({None: ([dict(GOOD_CONTACT)], None)})
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:7301"):
            reached.append(1)
            return httpx.Response(404, json={"code": "x", "message": LONG})
        return inner(request)

    _stub_client(monkeypatch, handler)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the re-fetch stub was never reached"
    assert job.status == "done", job.error
    rows = _rows_of(job, "events")
    assert len(rows) == 1, _sample(job)
    assert _count_a(rows[0]["reason"]) <= 300, len(rows[0]["reason"])
    db.close()


def test_ac_44_20_a_long_vendor_message_is_capped_in_the_422(soft_client, monkeypatch):
    state = _state()
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    base = _handler(state)
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/channel"):
            reached.append(1)
            return httpx.Response(404, json={"code": "x", "message": LONG})
        return base(request)

    _patch_client_factory(monkeypatch, handler)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert reached, "the channel stub was never reached"
    assert res.status_code == 422, (res.status_code, res.text)
    assert _count_a(res.text) <= 300, len(res.text)


@pytest.mark.parametrize("message", [{"a": "MARKER-OBJ"}, ["MARKER-LIST"]], ids=["dict", "list"])
def test_ac_44_11_a_vendor_message_that_is_not_a_string_gives_fixed_text(session_factory, monkeypatch, message):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    handler = _error_handler({"code": "x", "message": message})
    _stub_client(monkeypatch, handler)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")

    run_migration_job(db, job)
    db.refresh(job)

    assert handler.reached, "the contact list stub was never reached"
    assert job.status == "failed", job.status
    _assert_no_markers(json.dumps([job.error, job.logs_json], default=str))
    db.close()


# ── more odd answers become a source error ──────────────────────────────────


def _channel_answer(state, body):
    base = _handler(state)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/channel") and state.get("odd"):
            state["odd_reached"] = state.get("odd_reached", 0) + 1
            return httpx.Response(200, json=body)
        return base(request)

    return handler


def test_ac_44_20_a_pagination_that_is_not_an_object_is_a_422_on_channel_map(soft_client, monkeypatch):
    state = _state()
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    _patch_client_factory(monkeypatch, _channel_answer(state, {"items": [], "pagination": 5}))
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    state["odd"] = True

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert state.get("odd_reached"), "the odd answer was never served"
    assert res.status_code == 422, (res.status_code, res.text)
    assert "channelMap" in res.json()["detail"]["fieldErrors"], res.text


def test_ac_44_01_a_pagination_that_is_not_an_object_does_not_fail_preflight(soft_client, monkeypatch):
    state = _state()
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    _patch_client_factory(monkeypatch, _channel_answer(state, {"items": [], "pagination": 5}))
    state["odd"] = True

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert state.get("odd_reached"), "the odd answer was never served"
    assert res.status_code == 200, (res.status_code, res.text)


def test_ac_44_11_a_channels_answer_whose_items_is_not_a_list_skips_that_identity_row(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    inner = _pages_handler_full({None: ([dict(GOOD_CONTACT)], None)})
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:7301/channels"):
            reached.append(1)
            return httpx.Response(200, json={"items": 5})
        return inner(request)

    _stub_client(monkeypatch, handler)
    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")

    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the channels stub was never reached"
    assert job.status == "done", job.error
    rows = _rows_of(job, "identities")
    assert len(rows) == 1 and rows[0]["sourceId"] == "7301", _sample(job)
    db.close()


# ── pin: with no matching dry run, that answer wins over "in progress" ──────


def test_ac_44_20_a_run_with_no_dry_run_while_a_job_is_in_progress_answers_dry_run_required(
    soft_client, monkeypatch, session_factory
):
    from app.models.background_job import JOB_RUNNING, BackgroundJob
    from modules.omnichannel.services.migration_service import MIGRATION_JOB_TYPE

    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())
    db = session_factory()
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
            payload_json={"workspaceId": ws_id, "mode": "dry_run"},
        )
    )
    db.commit()
    db.close()

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 409, (res.status_code, res.text)
    assert res.json()["detail"]["reason"] == "dry_run_required", res.text

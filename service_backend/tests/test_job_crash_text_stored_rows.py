"""Plan 45, AC-45-05 - the error field of a job, its run row, or a snapshot a
gateway returns holds a fixed sentence with the class name, never the
exception's text or a log line."""
from __future__ import annotations

import json

import pytest

from app.models.background_job import BackgroundJob
from modules.autocount.doc_feed.vendor import DocFeedVendor, DocFeedVendorError
from modules.autocount.models import AcPullSnapshot, AcSyncRun
from tests.meetings_bot_fakes import FakeArtifacts, bot_stdout
from tests.test_autocount_line_fingerprint_sweep import RUN_MODE_INCREMENTAL, RUN_MODE_MANUAL, _Rig
from tests.test_meetings_bot_runner import (  # noqa: F401 - fixtures re-exported
    _prepare,
    _run as _bot_run,
    db as meetings_db,
    local_storage,
    stt_provider_stub,
)

from .s16_do_pull_helpers import (  # noqa: F401 - s16_isolation is an autouse fixture
    ENTITY_DO,
    ENTITY_GRN,
    build_env,
    day_ago,
    get_header,
    iso,
    post_build,
    s16_isolation,
    stored_snapshot,
)

SECRET = "MARKER-CRASH text"


class Marker(RuntimeError):
    pass


def _cols(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── doc-feed (DO / GRN) pull snapshot: snapshot.py :156 setup, :175, :178 ────
def _build_failing(client, db, monkeypatch, entity, patch):
    env = build_env(db, monkeypatch, feed=entity)
    patch(monkeypatch)
    built = post_build(client, env.key, entity=entity, fromDay=iso(day_ago(1)))
    assert built.status_code == 202, built.text
    snap = stored_snapshot(db, built.json()["snapshotId"])
    assert snap.status == "failed", snap.status
    job = db.get(BackgroundJob, snap.job_id)
    db.refresh(job)
    runs = db.query(AcSyncRun).filter(AcSyncRun.company_id == env.company.id).all()
    header = get_header(client, env.key, snap.id)
    assert header.status_code == 200, header.text

    assert "Marker" in (job.error or "") or "DocFeedVendorError" in (job.error or ""), job.error
    stored = [job.error, job.result_json, job.logs_json, _cols(snap)] + [_cols(r) for r in runs]
    assert runs and all(r.error for r in runs)
    for r in runs:
        assert "Marker" in r.error or "DocFeedVendorError" in r.error, r.error
    assert "MARKER" not in json.dumps(stored, default=str)
    assert "MARKER" not in header.text
    assert "autocount-wrapper.example.com" not in json.dumps(stored, default=str)


def _patch_setup(monkeypatch):
    import modules.autocount.doc_feed.snapshot as snapshot_module

    def boom(db, feed_row, **kw):
        raise Marker(SECRET)

    monkeypatch.setattr(snapshot_module, "resolve_vendor", boom)


def _patch_vendor_error(monkeypatch):
    def boom(self, feed, day):
        raise DocFeedVendorError(
            "http_status", f"https://autocount-wrapper.example.com/api/db1 answered {SECRET}"
        )

    monkeypatch.setattr(DocFeedVendor, "day_by_doc_date", boom)


def _patch_fetch(monkeypatch):
    def boom(self, feed, day):
        raise Marker(SECRET)

    monkeypatch.setattr(DocFeedVendor, "day_by_doc_date", boom)


@pytest.mark.parametrize("entity", [ENTITY_DO, ENTITY_GRN])
def test_ac_45_05_doc_feed_snapshot_setup_fault_stores_the_class_name_only(client, db, monkeypatch, entity):
    _build_failing(client, db, monkeypatch, entity, _patch_setup)


@pytest.mark.parametrize("entity", [ENTITY_DO, ENTITY_GRN])
def test_ac_45_05_doc_feed_snapshot_vendor_error_stores_the_class_name_only(client, db, monkeypatch, entity):
    _build_failing(client, db, monkeypatch, entity, _patch_vendor_error)


@pytest.mark.parametrize("entity", [ENTITY_DO, ENTITY_GRN])
def test_ac_45_05_doc_feed_snapshot_fetch_fault_stores_the_class_name_only(client, db, monkeypatch, entity):
    _build_failing(client, db, monkeypatch, entity, _patch_fetch)


# ── fingerprint sweep note on the run row (sync.py :1601) ────────────────────
def test_ac_45_05_fingerprint_sweep_failure_note_holds_the_class_name_only(session_factory):
    rig = _Rig(
        session_factory,
        fingerprint_query="SELECT nonsense FROM MARKER_TABLE GROUP BY d.doc_key",
    )
    try:
        rig.run(RUN_MODE_MANUAL)
        job, run = rig.run(RUN_MODE_INCREMENTAL)
        assert run.error and "fingerprint sweep failed" in run.error.lower(), run.error
        assert "OperationalError" in run.error, run.error
        assert "MARKER" not in json.dumps([run.error, job.error, job.result_json, job.logs_json], default=str)
    finally:
        rig.close()


# ── meetings.bot_run non-zero exit (bot_runner.py :581-582) ──────────────────
def test_ac_45_05_bot_exit_reason_from_the_bots_own_error_is_not_stored_on_the_job(meetings_db, monkeypatch):
    meeting = _prepare(meetings_db)
    job, _docker, _container = _bot_run(
        meetings_db, monkeypatch, meeting,
        lines=bot_stdout(reason=f"error:ValueError:{SECRET}"), exit_code=1,
        artifacts=FakeArtifacts({}),
    )
    assert job.status == "failed"
    assert job.error
    assert "MARKER" not in json.dumps([job.error, job.result_json, job.logs_json], default=str)
    assert "MARKER" in (meeting.status_reason or ""), "the meeting keeps the detail"


def test_ac_45_05_bot_exit_last_log_line_is_not_stored_on_the_job(meetings_db, monkeypatch):
    meeting = _prepare(meetings_db)
    job, _docker, _container = _bot_run(
        meetings_db, monkeypatch, meeting,
        lines=[f"{SECRET} from the container log"], exit_code=1,
        artifacts=FakeArtifacts({}),
    )
    assert job.status == "failed"
    assert job.error
    assert "MARKER" not in json.dumps([job.error, job.result_json, job.logs_json], default=str)
    assert "MARKER" in (meeting.status_reason or ""), "the meeting keeps the detail"

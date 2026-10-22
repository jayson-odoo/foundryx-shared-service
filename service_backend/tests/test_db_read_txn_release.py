"""Plan 34 (SS-IDLE-TXN-LEAK) - no app-DB transaction held open across
network I/O.

The prod deploy of #128 aborted twice: migration 0031 hit ``lock_timeout``
because sessions sat ``idle in transaction`` on ``app_autocount`` for minutes,
holding AccessShareLock on ``ac_company`` / ``ac_entity_config``. Every ORM
read autobegins a transaction; the ETL / preview / push paths then walked the
vendor API or POSTed to Sorento before the next commit, so the read
transaction (and its locks) lived for the whole walk.

The fix is ``app.database.release_read_transactions()``: it ends every
autobegun, write-free transaction the current thread holds, and each network
seam calls it right before its I/O. These tests pin:

- the helper itself (what it ends, what it must leave alone);
- every seam (the stub transport asserts the caller's session holds no open
  read transaction at the moment the request goes out);
- a real ``run_autocount_sync`` HTTP walk;
- ``application_name`` per process (api / worker / beat), so the DEPLOY.md
  lock-holder report names the owner;
- Postgres-only: ``pg_stat_activity`` shows the session ``idle``, not
  ``idle in transaction``, while the vendor request is in flight (skips
  without ``TEST_POSTGRES_URL``; CI has no Postgres).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Dict, List

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def scratch_session():
    """A file-less sqlite engine of our own (not the shared conftest
    StaticPool), so a write test can tell "committed" from "still pending"
    through a second, independent connection."""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _release() -> int:
    from app.database import release_read_transactions

    return release_read_transactions()


# ── the helper ────────────────────────────────────────────────────────────


def test_release_ends_an_autobegun_read_transaction(scratch_session):
    scratch_session.execute(text("SELECT 1"))
    assert scratch_session.in_transaction()

    assert _release() == 1

    assert not scratch_session.in_transaction()


def test_release_keeps_loaded_objects_unexpired(db):
    """Ending the read transaction must not expire what the caller already
    loaded: the walk keeps using ``company`` / ``config`` after the seam, and
    an expiry would turn every attribute access into a fresh SELECT that
    reopens the very transaction we just ended."""
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=str(uuid.uuid4()), database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    loaded = db.get(AcCompany, company.id)
    assert loaded.name == "Mocha"
    assert db.in_transaction()

    _release()

    assert not db.in_transaction()
    assert "name" in loaded.__dict__, "release expired a loaded object"
    assert loaded.name == "Mocha"
    assert not db.in_transaction(), "reading a loaded attribute reopened a transaction"


def test_release_leaves_a_flushed_write_open(scratch_session):
    scratch_session.execute(text("INSERT INTO t (id, v) VALUES (1, 'a')"))
    assert scratch_session.in_transaction()

    assert _release() == 0

    assert scratch_session.in_transaction(), "release committed someone's half-done write"
    scratch_session.rollback()
    assert scratch_session.execute(text("SELECT count(*) FROM t")).scalar() == 0


def test_release_leaves_a_read_after_a_write_open(scratch_session):
    scratch_session.execute(text("INSERT INTO t (id, v) VALUES (1, 'a')"))
    scratch_session.execute(text("SELECT v FROM t"))

    assert _release() == 0
    assert scratch_session.in_transaction()


def test_release_leaves_pending_unflushed_changes_open(db):
    db.execute(text("SELECT 1"))
    db.add(
        AcCompany(
            tenant_id=DEFAULT_TENANT_ID, connection_id=str(uuid.uuid4()),
            database_name="X", company_name="X", name="X", is_active=True,
        )
    )

    assert _release() == 0
    assert db.in_transaction()
    assert len(db.new) == 1


def test_release_leaves_an_explicit_begin_block_alone(scratch_session):
    with scratch_session.begin():
        scratch_session.execute(text("SELECT 1"))
        assert _release() == 0
        assert scratch_session.in_transaction()


def test_release_leaves_a_savepoint_alone(scratch_session):
    scratch_session.execute(text("SELECT 1"))
    with scratch_session.begin_nested():
        scratch_session.execute(text("SELECT 1"))
        assert _release() == 0
        assert scratch_session.in_transaction()
    scratch_session.rollback()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM t WHERE id = 1 FOR UPDATE",
        "SELECT id FROM t WHERE id = 1 FOR NO KEY UPDATE",
        "SELECT id FROM t WHERE id = 1 FOR SHARE",
        "SELECT pg_advisory_xact_lock(42)",
    ],
)
def test_release_leaves_a_locking_select_open(sql):
    """A row lock or a transaction-scoped advisory lock is a deliberate
    hold: ending the transaction would drop it under the caller. Only the
    statement text is classified, so a fake cursor is enough here (sqlite
    rejects these clauses)."""
    from app.database import _statement_is_plain_read

    assert _statement_is_plain_read("SELECT id FROM t") is True
    assert _statement_is_plain_read("  select 1") is True
    assert _statement_is_plain_read(sql) is False
    # Same clause after a newline / tab (how a formatted query renders it).
    assert _statement_is_plain_read(sql.replace(" FOR ", "\nFOR ").replace(" ", "\t", 1)) is False


def test_set_config_counts_as_a_write():
    """``set_config(.., true)`` is transaction-local, like ``SET LOCAL``:
    ending the transaction would silently drop the setting."""
    from app.database import _statement_is_plain_read

    assert _statement_is_plain_read("SELECT set_config('app.tenant', 'x', true)") is False


def _spy_commits(monkeypatch, session, *, raises: bool = False) -> List[str]:
    """Record (and optionally fail) every ``commit`` on ``session``. A spy,
    not a transaction-state check: sqlite refuses a cross-thread COMMIT on
    its own, which would hide a release that tried one (Postgres would not)."""
    calls: List[str] = []
    real_commit = session.commit

    def commit() -> None:
        calls.append(threading.current_thread().name)
        if raises:
            raise RuntimeError("commit refused")
        real_commit()

    monkeypatch.setattr(session, "commit", commit)
    return calls


def test_release_only_touches_the_calling_threads_sessions(scratch_session, monkeypatch):
    """A Session is not thread-safe: a release on one thread must never
    commit a session another thread is using (the Sorento / page-walk
    thread pools call the seams from pool threads)."""
    commits = _spy_commits(monkeypatch, scratch_session)
    scratch_session.execute(text("SELECT 1"))
    released: List[int] = []
    other = threading.Thread(target=lambda: released.append(_release()), name="pool-thread")
    other.start()
    other.join()

    assert commits == [], f"a release on another thread committed this session: {commits}"
    assert released == [0]
    assert scratch_session.in_transaction()


def test_release_only_touches_the_calling_contexts_sessions(scratch_session, monkeypatch):
    """The API runs the endpoint, the response serialization and get_db's
    close as separate threadpool hops, each in its own context copy, and a
    pool thread is reused across requests. A seam in request B must never
    commit request A's session just because A's endpoint ran on the same
    pool thread."""
    import contextvars

    commits = _spy_commits(monkeypatch, scratch_session)
    contextvars.copy_context().run(lambda: scratch_session.execute(text("SELECT 1")))
    released = contextvars.copy_context().run(_release)

    assert commits == [], "request B's seam committed request A's session"
    assert released == 0
    assert scratch_session.in_transaction()


def test_release_survives_a_commit_that_raises(scratch_session, db, monkeypatch, caplog):
    """A session whose commit fails is skipped with a warning; the release
    still ends every other read transaction and never raises into the
    caller's network call."""
    import logging

    _spy_commits(monkeypatch, scratch_session, raises=True)
    scratch_session.execute(text("SELECT 1"))
    db.execute(text("SELECT 1"))

    with caplog.at_level(logging.WARNING, logger="app.database"):
        released = _release()

    assert released == 1
    assert not db.in_transaction()
    assert any("could not end a read transaction" in r.getMessage() for r in caplog.records)


def test_release_skips_a_broken_session_and_never_raises(scratch_session, db):
    """Another session on this thread whose connection died (invalidated,
    or its transaction failed) is its owner's to roll back. Release must
    skip it - never raise into the caller's network call - and still end
    the healthy read transaction."""
    scratch_session.execute(text("SELECT 1"))
    scratch_session.connection().invalidate()
    db.execute(text("SELECT 1"))
    assert db.in_transaction()

    released = _release()

    assert released == 1
    assert not db.in_transaction()
    scratch_session.rollback()


# ── the seams ─────────────────────────────────────────────────────────────


def _recording_handler(db, seen: List[bool], body: Any = None, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(db.in_transaction())
        return httpx.Response(status, json=body if body is not None else {})

    return handler


def test_vendor_http_get_releases_the_read_transaction(db):
    from modules.autocount.http_source.client import HttpApiClient

    seen: List[bool] = []
    client = HttpApiClient(
        BASE_URL,
        transport=httpx.Client(transport=httpx.MockTransport(_recording_handler(db, seen, []))),
    )
    db.execute(text("SELECT 1"))
    assert db.in_transaction()

    client.get("/itembypage", {"page": 1})

    assert seen == [False], "the vendor GET went out with the read transaction still open"


def test_vendor_login_post_releases_the_read_transaction(db):
    from modules.autocount.client import AutoCountClient

    seen: List[bool] = []
    client = AutoCountClient(
        base_url=BASE_URL, app_id="app", user_id="u", password="p",
        transport=httpx.Client(
            transport=httpx.MockTransport(
                _recording_handler(db, seen, {"Status": True, "Data": {"Token": "t"}})
            )
        ),
    )
    db.execute(text("SELECT 1"))

    try:
        client.login()
    except Exception:  # noqa: BLE001 - only the transaction state at send time matters
        pass

    assert seen and seen[0] is False, "the vendor login POST went out inside the read transaction"


def test_sorento_push_releases_the_read_transaction(db):
    from modules.autocount.canonical.masters import CanonicalBrand
    from modules.autocount.canonical.masters import ENTITY_BRAND
    from modules.autocount.sinks_sorento import SorentoSink

    seen: List[bool] = []
    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(
            _recording_handler(
                db, seen,
                {"summary": {"created": 1}, "records": [{"source_ref": "MOCHA:S", "outcome": "created"}]},
            )
        ),
    )
    db.execute(text("SELECT 1"))

    sink.write_batch(
        [CanonicalBrand(source_ref="MOCHA:S", code="S", name="S")], request_id="req-1"
    )

    assert seen == [False], "the Sorento POST went out inside the read transaction"


def test_sorento_contract_probe_releases_the_read_transaction(db):
    from modules.autocount.canonical.masters import ENTITY_BRAND
    from modules.autocount.sinks_sorento import SorentoSink

    seen: List[bool] = []
    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(
            _recording_handler(db, seen, {"version": "2.10", "entities": ["brand"]})
        ),
    )
    db.execute(text("SELECT 1"))
    sink.fetch_contract_detail()
    db.execute(text("SELECT 1"))
    sink.fetch_contract()

    assert seen == [False, False], "the Sorento /contract probe went out inside the read transaction"


def test_external_sql_connection_releases_the_read_transaction(db):
    """``open_readonly`` is the one door every customer-DB query goes
    through (preview, header page, fingerprints, by-keys): the pool wait,
    the connect and every query after it can each take tens of seconds."""
    from modules.autocount.sql_source.runtime import open_readonly

    external = create_engine("sqlite:///:memory:", future=True)
    db.execute(text("SELECT 1"))
    assert db.in_transaction()
    try:
        with open_readonly(external) as conn:
            assert not db.in_transaction(), "a customer-DB query ran inside the app read transaction"
            conn.execute(text("SELECT 1"))
    finally:
        external.dispose()


def test_sql_line_fetch_releases_the_read_transaction_before_the_line_queries(db):
    """``_attach_lines`` runs after ``_prior_hashes`` re-read the app DB,
    and its thread-pool branch queries from OTHER threads - so it must end
    the caller's read transaction itself, on the caller's thread, first."""
    from modules.autocount.sql_source.source import SqlDbSource

    seen: List[bool] = []

    class _Probe:
        _engine = type("E", (), {"pool": object()})()

        def _read_lines(self, conn, key):  # sequential branch
            seen.append(db.in_transaction())
            return []

        def _read_lines_own_connection(self, key):  # thread-pool branch
            seen.append(db.in_transaction())
            return []

    db.execute(text("SELECT 1"))
    SqlDbSource._attach_lines(_Probe(), None, [{"K": "1"}, {"K": "2"}], "K")

    assert seen and not any(seen), "line queries ran while the app read transaction was open"


def test_sorento_provider_test_button_releases_the_read_transaction(db):
    from modules.autocount import sorento_provider

    seen: List[bool] = []
    transport = httpx.MockTransport(
        _recording_handler(db, seen, {"version": "2.10", "entities": []})
    )
    db.execute(text("SELECT 1"))
    try:
        sorento_provider.SorentoProvider().test(
            {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}, transport=transport,
        )
    except Exception:  # noqa: BLE001 - only the transaction state at send time matters
        pass

    assert seen and not any(seen), "the Sorento Test probe went out inside the read transaction"


def test_open_api_probe_releases_the_read_transaction(db):
    from modules.autocount.http_client import probe_open_connection

    seen: List[bool] = []
    client = httpx.Client(transport=httpx.MockTransport(_recording_handler(db, seen, [])))
    db.execute(text("SELECT 1"))

    probe_open_connection(BASE_URL, transport=client)

    assert seen == [False], "the open-API probe went out inside the read transaction"


def _concurrent_sink(db, seen: List[bool], entity_type: str):
    from modules.autocount.sinks_sorento import SorentoSink

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(db.in_transaction())
        body = json.loads(request.content or b"{}")
        refs = [r.get("source_ref") for r in body.get("records") or []] or list(
            body.get("source_refs") or []
        )
        return httpx.Response(
            200,
            json={
                "summary": {"created": len(refs)},
                "records": [{"source_ref": r, "outcome": "created"} for r in refs],
                "deleted": refs, "not_found": [],
            },
        )

    return SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=entity_type,
        transport=httpx.MockTransport(handler), batch_size=1, concurrency_config="2",
    )


def test_concurrent_sorento_push_releases_on_the_calling_thread(db):
    """At sinkConcurrency > 1 the POSTs run on pool threads, whose release
    cannot touch the caller's session: the caller must end its own read
    transaction before it submits the chunks."""
    from modules.autocount.canonical.masters import CanonicalBrand, ENTITY_BRAND

    seen: List[bool] = []
    sink = _concurrent_sink(db, seen, ENTITY_BRAND)
    db.execute(text("SELECT 1"))

    sink.write_batch(
        [CanonicalBrand(source_ref=f"MOCHA:{i}", code=str(i), name=str(i)) for i in range(2)],
        request_id="req-1",
    )

    assert len(seen) == 2
    assert not any(seen), "a concurrent Sorento POST went out inside the caller's read transaction"


def test_concurrent_sorento_delete_releases_on_the_calling_thread(db):
    seen: List[bool] = []
    sink = _concurrent_sink(db, seen, ENTITY_PRODUCT)
    db.execute(text("SELECT 1"))

    try:
        sink.delete_batch(["MOCHA:A", "MOCHA:B"])
    except Exception:  # noqa: BLE001 - only the transaction state at send time matters
        pass

    assert len(seen) == 2
    assert not any(seen), "a concurrent Sorento delete went out inside the caller's read transaction"


def test_concurrent_page_batch_releases_on_the_calling_thread(db):
    from modules.autocount.http_source.source import HttpApiSource

    seen: List[bool] = []

    class _Probe:
        def _fetch_page_concurrent(self, path, page, page_size):
            seen.append(db.in_transaction())
            return page

    db.execute(text("SELECT 1"))
    HttpApiSource._run_concurrent_batch(_Probe(), "/itembypage", 10, [1, 2])

    assert len(seen) == 2
    assert not any(seen), "concurrent vendor pages went out inside the caller's read transaction"


# ── a real ETL walk ───────────────────────────────────────────────────────


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _http_raw(connection_id: str) -> Dict[str, Any]:
    return {
        "sourceImpl": "autocount_http",
        "connectionId": connection_id,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }


def test_scheduled_http_walk_never_holds_a_read_transaction_across_vendor_requests(
    db, monkeypatch
):
    """The prod lock signature (pid=96, 7.5 min, AccessShareLock on
    ``ac_company`` + ``ac_entity_config``): ``run_autocount_sync`` re-reads
    the config and company after its log commit, then walks every vendor
    page before the next commit. Every page request must go out with no
    read transaction open on the job's session."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.services.etl_service import EtlService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    seen: List[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(db.in_transaction())
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200,
            json={
                "TotalCount": 3, "Page": page, "PageSize": 1, "TotalPages": 3,
                "Data": [{"ItemCode": f"A{page}", "LastModified": "2026-08-01T09:00:00", "IsActive": "T"}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True, sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id))
    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )

    run_autocount_sync(db, job)

    assert len(seen) >= 3, f"expected the 3-page walk, saw {len(seen)} requests"
    assert not any(seen), (
        f"{sum(seen)} of {len(seen)} vendor requests went out with the job's read transaction open"
    )


# ── application_name per process ──────────────────────────────────────────


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["/usr/local/bin/gunicorn", "app.main:app", "--worker-class", "uvicorn.workers.UvicornWorker"], "foundryx-api"),
        # start.sh: `exec python -m gunicorn app.main:app ...`
        (["/usr/local/lib/python3.12/site-packages/gunicorn/__main__.py", "app.main:app"], "foundryx-api"),
        (["/usr/local/lib/python3.12/site-packages/celery/__main__.py", "-A", "app.workflow_engine.worker", "beat"], "foundryx-beat"),
        (["/usr/local/bin/uvicorn", "app.main:app", "--reload"], "foundryx-api"),
        (["/usr/local/bin/celery", "-A", "app.workflow_engine.worker", "worker", "-Q", "jobs", "-c", "2"], "foundryx-worker-jobs"),
        (["/usr/local/bin/celery", "-A", "app.workflow_engine.worker", "worker", "-Q", "workflow", "--loglevel", "info"], "foundryx-worker-workflow"),
        (["/usr/local/bin/celery", "-A", "modules.omnichannel.worker", "worker", "-Q", "omni"], "foundryx-worker-omni"),
        (["/usr/local/bin/celery", "-A", "app.workflow_engine.worker", "beat", "--loglevel", "info"], "foundryx-beat"),
        (["/app/scripts/bootstrap_db.py"], "foundryx-bootstrap_db"),
    ],
)
def test_application_name_names_the_process(monkeypatch, argv, expected):
    from app import database
    from app.config import settings

    monkeypatch.setattr(settings, "db_application_name", "", raising=False)
    monkeypatch.setattr(database.sys, "argv", argv)

    assert database.process_application_name() == expected


def test_application_name_override_wins_and_is_capped(monkeypatch):
    from app import database
    from app.config import settings

    monkeypatch.setattr(settings, "db_application_name", "x" * 100, raising=False)

    assert database.process_application_name() == "x" * 63


def test_app_engine_connect_args_carry_application_name_on_postgres_only(monkeypatch):
    from app import database
    from app.config import settings

    monkeypatch.setattr(settings, "db_application_name", "foundryx-api", raising=False)
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@localhost/x")
    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 0)
    monkeypatch.setattr(settings, "worker_db_statement_timeout_seconds", 0)
    monkeypatch.setattr(settings, "worker_db_idle_in_transaction_session_timeout_seconds", 0)
    assert database.app_connect_args() == {"application_name": "foundryx-api"}

    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 5)
    assert database.app_connect_args() == {
        "application_name": "foundryx-api",
        "options": "-c lock_timeout=5000",
    }

    monkeypatch.setattr(settings, "database_url", "sqlite://")
    assert database.app_connect_args() == {}


# ── Postgres: pg_stat_activity is the ground truth ────────────────────────


PG_URL = os.environ.get("TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL unset (CI has no Postgres)")
def test_pg_stat_activity_shows_idle_not_idle_in_transaction_during_the_vendor_get():
    from modules.autocount.http_source.client import HttpApiClient

    app_name = f"txn-leak-test-{uuid.uuid4().hex[:8]}"
    engine = create_engine(PG_URL, connect_args={"application_name": app_name})
    observer = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    session = sessionmaker(bind=engine)()
    states: List[str] = []

    def state() -> str:
        with observer.connect() as conn:
            return conn.execute(
                text("SELECT state FROM pg_stat_activity WHERE application_name = :n"),
                {"n": app_name},
            ).scalar_one()

    def handler(request: httpx.Request) -> httpx.Response:
        states.append(state())
        return httpx.Response(200, json=[])

    try:
        session.execute(text("SELECT count(*) FROM pg_class"))
        assert state() == "idle in transaction"  # control: the leak shape

        HttpApiClient(
            BASE_URL, transport=httpx.Client(transport=httpx.MockTransport(handler))
        ).get("/itembypage", {"page": 1})

        assert states == ["idle"], f"pg_stat_activity during the vendor GET: {states}"
    finally:
        session.close()
        engine.dispose()
        observer.dispose()

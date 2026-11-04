"""RED tests: an API request that waits on a row lock ends in a clean, bounded
"busy" answer instead of hanging or surfacing a bare 500.

Contract pinned here:
1. ``api_db_lock_timeout_seconds`` (default 10, 0 disables, floor >= 0). Only
   the API process (application name ``foundryx-api``) carries
   ``-c lock_timeout=<ms>`` in the libpq ``options`` connect arg, merged into
   the single options string with any worker options. bootstrap_db, workers,
   beat and scripts never get it (an explicit ``options`` overrides PGOPTIONS).
2. A Postgres lock timeout (SQLSTATE 55P03) inside a request answers 503 with
   ``Retry-After`` and CORS headers; ``/api/v1/`` uses the gateway envelope with
   code ``busy_try_again``. Other DB errors stay 500.
3. ``app.database.allow_long_lock_wait(db)``: ``SET lock_timeout = 0`` then
   ``RESET lock_timeout`` on Postgres (RESET even when the body raises), a
   no-op on sqlite. Entered by App Store install/update/uninstall (core and
   platform), tenant purge and storage-migration Complete.
"""
from __future__ import annotations

import contextlib
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.conftest import (
    ACTIVE_EMAIL,
    ACTIVE_PASSWORD,
    PLATFORM_EMAIL,
    PLATFORM_PASSWORD,
)

PG_URL = "postgresql://u:p@localhost/db"
BUSY_MESSAGE = "This record is busy with another change. Please try again in a moment."


# ---- a. connect args -------------------------------------------------------


def _zero_worker_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", PG_URL, raising=False)
    for name in (
        "worker_db_statement_timeout_seconds",
        "worker_db_lock_timeout_seconds",
        "worker_db_idle_in_transaction_session_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, 0, raising=False)
    return settings


def _args_for(monkeypatch, process_name):
    from app import database

    monkeypatch.setattr(database, "process_application_name", lambda: process_name)
    return database.app_connect_args(PG_URL)


def test_setting_defaults_to_ten_seconds_and_floors_at_zero(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("API_DB_LOCK_TIMEOUT_SECONDS", raising=False)
    assert Settings().api_db_lock_timeout_seconds == 10
    monkeypatch.setenv("API_DB_LOCK_TIMEOUT_SECONDS", "0")
    assert Settings().api_db_lock_timeout_seconds == 0
    monkeypatch.setenv("API_DB_LOCK_TIMEOUT_SECONDS", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_api_process_gets_lock_timeout_in_milliseconds(monkeypatch):
    settings = _zero_worker_settings(monkeypatch)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 10, raising=False)
    args = _args_for(monkeypatch, "foundryx-api")
    assert "-c lock_timeout=10000" in args["options"]
    assert args["application_name"] == "foundryx-api"
    assert "statement_timeout" not in args["options"]


def test_api_lock_timeout_merges_with_worker_options_in_one_string(monkeypatch):
    settings = _zero_worker_settings(monkeypatch)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 10, raising=False)
    monkeypatch.setattr(settings, "worker_db_statement_timeout_seconds", 120, raising=False)
    monkeypatch.setattr(
        settings, "worker_db_idle_in_transaction_session_timeout_seconds", 300, raising=False
    )
    args = _args_for(monkeypatch, "foundryx-api")
    options = args["options"]
    assert options.count("lock_timeout=10000") == 1
    assert "-c statement_timeout=120000" in options
    assert "-c idle_in_transaction_session_timeout=300000" in options
    assert sum(1 for k in args if k == "options") == 1


def test_zero_disables_the_api_lock_timeout(monkeypatch):
    settings = _zero_worker_settings(monkeypatch)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 0, raising=False)
    args = _args_for(monkeypatch, "foundryx-api")
    assert "options" not in args


@pytest.mark.parametrize(
    "process_name",
    [
        "foundryx-bootstrap_db",
        "foundryx-worker",
        "foundryx-worker-workflow+jobs",
        "foundryx-beat",
        "foundryx-some_script",
    ],
)
def test_non_api_processes_get_nothing_added(monkeypatch, process_name):
    settings = _zero_worker_settings(monkeypatch)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 10, raising=False)
    args = _args_for(monkeypatch, process_name)
    assert "options" not in args
    assert args == {"application_name": process_name}


def test_non_api_process_keeps_its_own_worker_lock_timeout(monkeypatch):
    settings = _zero_worker_settings(monkeypatch)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 10, raising=False)
    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 30, raising=False)
    args = _args_for(monkeypatch, "foundryx-worker")
    assert args["options"] == "-c lock_timeout=30000"


# ---- b. handler ------------------------------------------------------------


class _FakeOrig(Exception):
    def __init__(self, pgcode):
        super().__init__("fake driver error")
        self.pgcode = pgcode
        self.sqlstate = pgcode


@pytest.fixture
def probe_routes(client):
    from app.main import app

    def lock_timeout():
        raise OperationalError("UPDATE t SET v = 1", None, _FakeOrig("55P03"))

    def other_error():
        raise OperationalError("UPDATE t SET v = 1", None, _FakeOrig("40001"))

    before = len(app.router.routes)
    for path in ("/_lockprobe/internal", "/api/v1/_lockprobe"):
        app.add_api_route(path + "/busy", lock_timeout, methods=["GET"])
        app.add_api_route(path + "/other", other_error, methods=["GET"])
    yield TestClient(app, raise_server_exceptions=False)
    del app.router.routes[before:]


ORIGIN = {"Origin": "http://localhost:3001"}


def test_lock_timeout_answers_503_with_retry_after_and_cors(probe_routes):
    res = probe_routes.get("/_lockprobe/internal/busy", headers=ORIGIN)
    assert res.status_code == 503, res.text
    assert res.headers["retry-after"].isdigit()
    assert res.json() == {"detail": BUSY_MESSAGE}
    assert res.headers["access-control-allow-origin"] == ORIGIN["Origin"]


def test_lock_timeout_under_gateway_uses_the_error_envelope(probe_routes):
    res = probe_routes.get("/api/v1/_lockprobe/busy", headers=ORIGIN)
    assert res.status_code == 503, res.text
    assert res.headers["retry-after"].isdigit()
    assert res.json() == {"error": {"code": "busy_try_again", "message": BUSY_MESSAGE}}
    assert res.headers["access-control-allow-origin"] == ORIGIN["Origin"]


def test_other_database_errors_stay_500(probe_routes):
    res = probe_routes.get("/_lockprobe/internal/other", headers=ORIGIN)
    assert res.status_code == 500
    assert "retry-after" not in res.headers
    res = probe_routes.get("/api/v1/_lockprobe/other")
    assert res.status_code == 500


# ---- c. opt-out helper -----------------------------------------------------


class _FakeDb:
    """Records every statement run through the session OR its connection."""

    def __init__(self, dialect):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.info: dict = {}
        self.executed: list[str] = []

    def get_bind(self, *a, **k):
        return self.bind

    def execute(self, statement, *a, **k):
        self.executed.append(" ".join(str(statement).lower().split()))

    def connection(self, *a, **k):
        return SimpleNamespace(execute=self.execute, dialect=self.bind.dialect)


def _assert_only_transaction_scoped(executed):
    assert executed, "entering must raise the limit for the current transaction"
    for sql in executed:
        assert sql.startswith("set local lock_timeout"), sql
        assert "reset" not in sql


def test_helper_raises_the_limit_per_transaction_and_flags_the_session(monkeypatch):
    from app.config import settings
    from app.database import allow_long_lock_wait

    monkeypatch.setitem(settings.__dict__, "api_db_long_lock_timeout_seconds", 300)
    db = _FakeDb("postgresql")
    with allow_long_lock_wait(db):
        assert db.info, "the session carries a flag while the opt-out is active"
        _assert_only_transaction_scoped(db.executed)
        assert "300000" in db.executed[0]
    assert not db.info, "the flag is cleared on leaving"
    _assert_only_transaction_scoped(db.executed)  # no session-level SET, no RESET


def test_helper_clears_the_flag_even_when_the_body_raises():
    from app.database import allow_long_lock_wait

    db = _FakeDb("postgresql")
    with pytest.raises(RuntimeError):
        with allow_long_lock_wait(db):
            assert db.info
            raise RuntimeError("boom")
    assert not db.info
    _assert_only_transaction_scoped(db.executed)


def test_helper_is_a_noop_on_sqlite():
    from app.database import allow_long_lock_wait

    db = _FakeDb("sqlite")
    with allow_long_lock_wait(db):
        assert not db.info
    assert db.executed == []
    assert not db.info


# ---- d. routes use the helper ---------------------------------------------


@pytest.fixture
def lock_wait_recorder(monkeypatch):
    from app import database

    original = database.allow_long_lock_wait
    entered: list[object] = []

    @contextlib.contextmanager
    def recorder(db):
        entered.append(db)
        yield

    # Routers/services may import the helper by name; swap every reference.
    for module in list(sys.modules.values()):
        if getattr(module, "allow_long_lock_wait", None) is original:
            monkeypatch.setattr(module, "allow_long_lock_wait", recorder)
    return entered


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _operator(client):
    return _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")


def _tenant(client, slug):
    op = _operator(client)
    res = client.post(
        "/platform/tenants",
        json={
            "name": slug,
            "slug": slug,
            "contactName": "Kay Meister",
            "contactEmail": f"admin-{slug}@example.com",
            "adminName": "Kay Meister",
            "adminEmail": f"admin-{slug}@example.com",
            "adminPassword": "ChangeMe1!",
        },
        headers=op,
    )
    assert res.status_code == 201, res.text
    admin = _login(client, f"admin-{slug}@example.com", "ChangeMe1!", slug)
    return res.json()["id"], op, admin


@pytest.mark.parametrize("action", ["install", "update"])
def test_core_app_store_install_update_allow_long_lock_wait(client, lock_wait_recorder, action):
    _, _, admin = _tenant(client, f"lw-core-{action}")
    client.post(f"/app-store/modules/omnichannel/{action}", headers=admin)
    assert len(lock_wait_recorder) == 1


def test_core_app_store_uninstall_allows_long_lock_wait(client, lock_wait_recorder):
    _, _, admin = _tenant(client, "lw-core-uninstall")
    client.post(
        "/app-store/modules/omnichannel/uninstall",
        json={"confirmName": "omnichannel"},
        headers=admin,
    )
    assert len(lock_wait_recorder) == 1


@pytest.mark.parametrize("action", ["install", "update"])
def test_platform_module_install_update_allow_long_lock_wait(client, lock_wait_recorder, action):
    tenant_id, op, _ = _tenant(client, f"lw-plat-{action}")
    client.post(f"/platform/tenants/{tenant_id}/modules/omnichannel/{action}", headers=op)
    assert len(lock_wait_recorder) == 1


def test_platform_module_uninstall_allows_long_lock_wait(client, lock_wait_recorder):
    tenant_id, op, _ = _tenant(client, "lw-plat-uninstall")
    client.post(
        f"/platform/tenants/{tenant_id}/modules/omnichannel/uninstall",
        json={"confirmName": "omnichannel"},
        headers=op,
    )
    assert len(lock_wait_recorder) == 1


def test_tenant_purge_allows_long_lock_wait(client, lock_wait_recorder):
    tenant_id, op, _ = _tenant(client, "lw-purge")
    assert client.post(f"/platform/tenants/{tenant_id}/archive", headers=op).status_code == 200
    client.post(
        f"/platform/tenants/{tenant_id}/purge", json={"confirmSlug": "lw-purge"}, headers=op
    )
    assert len(lock_wait_recorder) == 1


def test_storage_migration_complete_allows_long_lock_wait(client, lock_wait_recorder):
    headers = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    # Unknown job id: the route is entered (and the helper with it) before the
    # service answers its not-found.
    client.post(f"/jobs/{uuid.uuid4()}/complete", headers=headers)
    assert len(lock_wait_recorder) == 1


# ---- e. live Postgres probe (skips when no local Postgres) ----------------


def test_live_postgres_lock_timeout_surfaces_as_55p03():
    import time

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError as OpErr

    from app.db_errors import error_code_of

    dbname = f"foundryx_lockprobe_{uuid.uuid4().hex[:8]}"
    try:
        admin = create_engine("postgresql://localhost/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
            c.execute(text(f"CREATE DATABASE {dbname}"))
    except Exception as exc:  # noqa: BLE001 - no local Postgres: skip
        pytest.skip(f"no local Postgres to probe: {exc!r}")
    url = f"postgresql://localhost/{dbname}"
    a = create_engine(url)
    b = create_engine(url, connect_args={"options": "-c lock_timeout=1000"})
    try:
        with a.begin() as c:
            c.execute(text("CREATE TABLE t (id int PRIMARY KEY, v int)"))
            c.execute(text("INSERT INTO t VALUES (1, 0)"))
        holder = a.connect()
        holder.execute(text("SELECT * FROM t WHERE id = 1 FOR UPDATE"))
        started = time.monotonic()
        with pytest.raises(OpErr) as caught:
            with b.begin() as c:
                c.execute(text("UPDATE t SET v = 1 WHERE id = 1"))
        assert time.monotonic() - started < 5
        assert error_code_of(caught.value) == "55P03"
        holder.rollback()
        holder.close()
    finally:
        a.dispose()
        b.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
        admin.dispose()


# ---- f. live Postgres: the real engine args, handler and opt-out ----------


@pytest.fixture
def live_pg(monkeypatch):
    """Scratch Postgres database + an engine built with the app's REAL
    connect args as the API process with a 1 s lock limit. Skips without a
    local Postgres."""
    from sqlalchemy import create_engine, text

    from app import database
    from app.config import settings

    dbname = f"foundryx_lockprobe_{uuid.uuid4().hex[:8]}"
    try:
        admin = create_engine("postgresql://localhost/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
            c.execute(text(f"CREATE DATABASE {dbname}"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no local Postgres to probe: {exc!r}")
    url = f"postgresql://localhost/{dbname}"
    monkeypatch.setattr(database, "process_application_name", lambda: "foundryx-api")
    for name in (
        "worker_db_statement_timeout_seconds",
        "worker_db_lock_timeout_seconds",
        "worker_db_idle_in_transaction_session_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, 0)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 1)
    engine = database.build_engine(url)
    other = create_engine(url)
    with other.begin() as c:
        c.execute(text("CREATE TABLE t (id int PRIMARY KEY, v int)"))
        c.execute(text("INSERT INTO t VALUES (1, 0)"))
    holder = other.connect()
    holder.execute(text("SELECT * FROM t WHERE id = 1 FOR UPDATE"))
    try:
        yield SimpleNamespace(engine=engine, holder=holder)
    finally:
        holder.close()
        engine.dispose()
        other.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
        admin.dispose()


def _update(session):
    from sqlalchemy import text

    session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))


def _show_limit(session):
    from sqlalchemy import text

    return session.execute(text("SHOW lock_timeout")).scalar()


def test_live_session_update_hits_the_api_lock_limit(live_pg):
    import time

    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from app.db_errors import error_code_of

    session = Session(live_pg.engine)
    started = time.monotonic()
    with pytest.raises(DBAPIError) as caught:
        _update(session)
    elapsed = time.monotonic() - started
    session.rollback()
    session.close()
    assert error_code_of(caught.value) == "55P03"
    assert 0.8 < elapsed < 3, elapsed


def test_live_lock_timeout_through_the_real_handler_is_503(live_pg):
    from app.main import app
    from sqlalchemy.orm import Session

    def touch():
        session = Session(live_pg.engine)
        try:
            _update(session)
        finally:
            session.close()

    before = len(app.router.routes)
    app.add_api_route("/_lockprobe/live", touch, methods=["GET"])
    try:
        res = TestClient(app, raise_server_exceptions=False).get(
            "/_lockprobe/live", headers=ORIGIN
        )
    finally:
        del app.router.routes[before:]
    assert res.status_code == 503, res.text
    assert res.headers["retry-after"].isdigit()
    assert res.json() == {"detail": BUSY_MESSAGE}
    assert res.headers["access-control-allow-origin"] == ORIGIN["Origin"]


def test_live_opt_out_waits_past_the_limit_then_restores_it(live_pg):
    import threading
    import time

    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    session = Session(live_pg.engine)
    assert _show_limit(session) == "1s"
    session.rollback()
    threading.Timer(2.0, live_pg.holder.commit).start()
    started = time.monotonic()
    with allow_long_lock_wait(session):
        _update(session)
        session.commit()
    elapsed = time.monotonic() - started
    assert elapsed > 1.5, elapsed  # waited past the 1 s limit, then succeeded
    assert _show_limit(session) == "1s"
    session.close()


def test_live_opt_out_restores_the_limit_after_a_rollback(live_pg):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    live_pg.holder.rollback()  # no contention needed here
    session = Session(live_pg.engine)
    with allow_long_lock_wait(session):
        with pytest.raises(DBAPIError):
            session.execute(text("SELECT 1/0"))
        session.rollback()
    assert _show_limit(session) == "1s"
    assert session.execute(text("SELECT 1")).scalar() == 1
    session.close()


# ---- g. PR 203 round 1: the opt-out never leaves a pooled connection unbounded


def test_long_limit_setting_default_and_floor(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("API_DB_LOCK_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("API_DB_LONG_LOCK_TIMEOUT_SECONDS", raising=False)
    assert Settings().api_db_long_lock_timeout_seconds == 300
    monkeypatch.setenv("API_DB_LOCK_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("API_DB_LONG_LOCK_TIMEOUT_SECONDS", "5")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("API_DB_LONG_LOCK_TIMEOUT_SECONDS", "10")
    assert Settings().api_db_long_lock_timeout_seconds == 10


def test_busy_warning_logs_the_route_template_not_the_concrete_path(client, caplog):
    import logging

    from app.main import app

    secret = "s3cr3t-token-value"

    def busy(token: str):
        raise OperationalError("UPDATE t SET v = 1", None, _FakeOrig("55P03"))

    before = len(app.router.routes)
    app.add_api_route("/_lockprobe/by-token/{token}", busy, methods=["GET"])
    try:
        with caplog.at_level(logging.WARNING):
            res = TestClient(app, raise_server_exceptions=False).get(
                f"/_lockprobe/by-token/{secret}"
            )
    finally:
        del app.router.routes[before:]
    assert res.status_code == 503
    text_logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/_lockprobe/by-token/{token}" in text_logged
    assert secret not in text_logged


@pytest.fixture
def live_pg_long(monkeypatch):
    """Like ``live_pg`` but API limit 1 s, long limit 3 s, a 3-connection pool."""
    from sqlalchemy import create_engine, text

    from app import database
    from app.config import settings

    dbname = f"foundryx_lockprobe_{uuid.uuid4().hex[:8]}"
    try:
        admin = create_engine("postgresql://localhost/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f"CREATE DATABASE {dbname}"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no local Postgres to probe: {exc!r}")
    url = f"postgresql://localhost/{dbname}"
    monkeypatch.setattr(database, "process_application_name", lambda: "foundryx-api")
    for name in (
        "worker_db_statement_timeout_seconds",
        "worker_db_lock_timeout_seconds",
        "worker_db_idle_in_transaction_session_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, 0)
    monkeypatch.setattr(settings, "api_db_lock_timeout_seconds", 1)
    # The field may not exist yet (red run): set it on the instance directly.
    monkeypatch.setitem(settings.__dict__, "api_db_long_lock_timeout_seconds", 3)
    engine = database.build_engine(url, pool_size=3, max_overflow=0)
    other = create_engine(url)
    with other.begin() as c:
        c.execute(text("CREATE TABLE t (id int PRIMARY KEY, v int)"))
        c.execute(text("INSERT INTO t VALUES (1, 0)"))
    holder = other.connect()
    holder.execute(text("SELECT * FROM t WHERE id = 1 FOR UPDATE"))
    try:
        yield SimpleNamespace(engine=engine, holder=holder)
    finally:
        holder.close()
        engine.dispose()
        other.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
        admin.dispose()


def _fill_pool(engine, n=3):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    sessions = [Session(engine) for _ in range(n)]
    for s in sessions:
        s.execute(text("SELECT 1"))
    for s in sessions:
        s.close()
    assert engine.pool.checkedin() >= 2


def _idle_limits(engine):
    conns = [engine.raw_connection() for _ in range(engine.pool.checkedin())]
    try:
        limits = []
        for rc in conns:
            cur = rc.cursor()
            cur.execute("SHOW lock_timeout")
            limits.append(cur.fetchone()[0])
            cur.close()
            rc.rollback()
        return limits
    finally:
        for rc in conns:
            rc.close()


def test_live_pool_stays_bounded_after_a_committing_opt_out(live_pg_long):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    live_pg_long.holder.rollback()
    _fill_pool(live_pg_long.engine)
    session = Session(live_pg_long.engine)
    session.execute(text("SELECT 1"))  # dependency hop
    with allow_long_lock_wait(session):
        session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))
        session.commit()
        session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))
        session.commit()
        session.execute(text("SELECT v FROM t"))  # response refresh
    session.close()  # what get_db does
    limits = _idle_limits(live_pg_long.engine)
    assert len(limits) >= 2
    assert limits == ["1s"] * len(limits), limits


def test_live_opt_out_survives_a_commit_inside_the_block(live_pg_long):
    import threading
    import time

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    session = Session(live_pg_long.engine)
    timer = threading.Timer(2.0, live_pg_long.holder.commit)
    try:
        with allow_long_lock_wait(session):
            session.execute(text("SELECT 1"))
            session.commit()  # the opt-out must still hold in the next transaction
            timer.start()
            started = time.monotonic()
            session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))
            session.commit()
            elapsed = time.monotonic() - started
    finally:
        timer.cancel()
        session.close()
    assert elapsed > 1.5, elapsed


def test_live_opt_out_has_a_ceiling(live_pg_long):
    import threading
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait
    from app.db_errors import error_code_of

    session = Session(live_pg_long.engine)
    # Safety net so a regression (unbounded wait) ends the test instead of hanging.
    timer = threading.Timer(7.0, live_pg_long.holder.commit)
    timer.start()
    started = time.monotonic()
    try:
        with allow_long_lock_wait(session):
            with pytest.raises(DBAPIError) as caught:
                session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()
        session.rollback()
        session.close()
    assert error_code_of(caught.value) == "55P03"
    assert 2.5 < elapsed < 5, elapsed


def test_live_pool_stays_bounded_after_a_rollback_inside_the_opt_out(live_pg_long):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    live_pg_long.holder.rollback()
    _fill_pool(live_pg_long.engine)
    session = Session(live_pg_long.engine)
    with allow_long_lock_wait(session):
        session.execute(text("UPDATE t SET v = v + 1 WHERE id = 1"))
        session.commit()
        with pytest.raises(DBAPIError):
            session.execute(text("SELECT 1/0"))
        session.rollback()
    session.close()
    limits = _idle_limits(live_pg_long.engine)
    assert len(limits) >= 2
    assert limits == ["1s"] * len(limits), limits


# ---- h. PR 203 round 3 ------------------------------------------------------


@pytest.mark.parametrize("long_value", ["0", "-1"])
@pytest.mark.parametrize("normal_value", ["0", "10"])
def test_long_limit_below_one_is_refused_even_when_the_normal_limit_is_off(
    monkeypatch, normal_value, long_value
):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("API_DB_LOCK_TIMEOUT_SECONDS", normal_value)
    monkeypatch.setenv("API_DB_LONG_LOCK_TIMEOUT_SECONDS", long_value)
    with pytest.raises(ValidationError):
        Settings()


def test_live_flag_applies_only_to_the_opted_out_session(live_pg_long):
    from sqlalchemy.orm import Session

    from app.database import allow_long_lock_wait

    live_pg_long.holder.rollback()
    a = Session(live_pg_long.engine)
    b = Session(live_pg_long.engine)
    try:
        with allow_long_lock_wait(a):
            assert _show_limit(a) == "3s"
            assert _show_limit(b) == "1s"
    finally:
        a.close()
        b.close()

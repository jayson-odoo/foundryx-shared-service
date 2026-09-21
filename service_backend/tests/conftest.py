"""Test fixtures: isolated in-memory SQLite + seeded default tenant/users.

Template-DB pattern (suite-speed PR, 2026-09): building the seeded schema
(``create_all`` x4 metadata bases + 7 seeders + module install) from scratch
for every single test dominated the suite's wall time (~3s/test). Instead,
each ``*_session_factory`` fixture is split in two:

- a SESSION-scoped ``_..._template`` fixture builds the seeded database
  exactly ONCE (same code path as before) and captures it as raw bytes via
  ``sqlite3.Connection.serialize()`` - one blob for the ``main`` database and
  one per ATTACHed schema database (``omni``, ``meetings``, ...);
- the function-scoped, publicly-named fixture (``session_factory`` etc, same
  name/signature every test already uses) creates a FRESH in-memory engine,
  ATTACHes the same schema names, then instant-copies the template in with
  ``sqlite3.Connection.deserialize()`` - a byte copy, not a re-run of DDL +
  seed queries.

``Connection.backup()`` only ever targets the destination's "main" database,
so it cannot fill a non-main ATTACHed schema from a live connection; the
serialize/deserialize pair supports an explicit ``name=`` on BOTH sides,
which is why it (not ``backup()``) drives this pattern. Isolation is
unchanged: every test still gets a private, pristine, fully-seeded SQLite
database - just built by copying bytes instead of executing SQL.
"""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func

from app.database import Base, get_db
from app.main import app
from app.models import (
    DEFAULT_TENANT_ID,
    Role,
    User,
    UserStatus,
)
from app.config import settings
from app.seed import (
    PLATFORM_ADMIN_EMAIL,
    PLATFORM_ADMIN_PASSWORD,
    seed_default_tenant,
    seed_permissions,
    seed_platform_admin,
    seed_platform_tenant,
    seed_statuses,
    seed_tenant_transitions,
    tenant_admin_grant,
)
from app.security import hash_password

# Tests run the omnichannel adapter in DEV mode (no live Meta Graph calls), even
# when META_* is set in a local .env - blank the Meta config for the test process.
settings.meta_app_id = ""
settings.meta_app_secret = ""
# No dispatcher thread under tests - outbox tests drive dispatch_pending()
# directly against the test session (the thread would hit the real DATABASE_URL).
settings.email_dispatcher_enabled = False
# No startup orphan sweep under tests either - ``TestClient(app)`` would open
# ``SessionLocal()`` against the real DATABASE_URL; the sweep's own tests force
# the flag per case and drive ``JobService`` against the test session.
settings.background_job_orphan_sweep_on_startup = False
# Tests must not pick up a platform SMTP connection from the local .env.
settings.platform_smtp_host = ""
# Nor a real LLM key: with no platform LLM connection seeded, the deterministic
# stub adapter answers (AC-BI-12) - the routine suite stays offline and free
# even on a machine whose .env carries a live provider key.
settings.platform_llm_api_key = ""
settings.grill_api_key = ""
# Workflow runs execute inline under tests (no Celery worker / Redis broker).
settings.celery_task_always_eager = True

ACTIVE_EMAIL = "demo@example.com"
ACTIVE_PASSWORD = "demo1234"
INACTIVE_EMAIL = "inactive@example.com"
INACTIVE_PASSWORD = "inactive1234"
PLATFORM_EMAIL = PLATFORM_ADMIN_EMAIL
PLATFORM_PASSWORD = PLATFORM_ADMIN_PASSWORD


def _capture_sqlite_databases(engine, names):
    """Serialize each named SQLite database (``"main"`` plus every ATTACHed
    schema name) off ``engine``'s single ``StaticPool`` connection into raw
    bytes - the "build once" half of the template-DB pattern (module
    docstring above). Returns ``{name: bytes}``."""
    raw = engine.raw_connection()
    try:
        conn = raw.dbapi_connection
        return {name: conn.serialize(name=name) for name in names}
    finally:
        raw.close()


def _restore_sqlite_databases(engine, blobs):
    """Instant-copy a captured template (``_capture_sqlite_databases``) onto
    a FRESH engine whose databases (``main`` + the same ATTACHed schema
    names) already exist (empty) - replaces ``create_all`` + seeding with a
    byte copy via ``sqlite3.Connection.deserialize``. ``engine`` must use the
    same ATTACHed names the blobs were captured under."""
    raw = engine.raw_connection()
    try:
        conn = raw.dbapi_connection
        for name, data in blobs.items():
            conn.deserialize(data, name=name)
    finally:
        raw.close()


@pytest.fixture(scope="session", autouse=True)
def _require_sqlite_serialize_support():
    """Fail fast, with a readable message, if this interpreter's ``sqlite3``
    binding lacks ``Connection.serialize``/``deserialize`` (Python 3.11+
    only) - the template-DB pattern above (``_capture_sqlite_databases`` /
    ``_restore_sqlite_databases``) depends on both. Without this guard, a
    missing binding first surfaces as an opaque ``AttributeError`` deep
    inside the first ``*_session_factory`` fixture build."""
    import sqlite3

    if not (
        hasattr(sqlite3.Connection, "serialize")
        and hasattr(sqlite3.Connection, "deserialize")
    ):
        pytest.fail(
            "backend tests need Python 3.11+ with sqlite deserialize support "
            "(sqlite3.Connection.serialize/deserialize) - the template-DB "
            "session_factory fixtures in tests/conftest.py depend on it.",
            pytrace=False,
        )


@pytest.fixture(scope="session", autouse=True)
def _register_storage_locations():
    """Populate the global storage-key location registry once, before any test
    snapshots/clears it. Mirrors app boot (``ensure_core_locations`` +
    ``load_modules``). ``ensure_core_locations`` is ``lazy_once``, so without an
    early full populate a migration test that first triggers it inside a
    clear/restore window would strand core locations for the drift test."""
    from app.storage_migration.core_locations import ensure_all_storage_locations

    ensure_all_storage_locations()
    yield


@pytest.fixture(scope="session", autouse=True)
def _register_deferred_actions():
    """Populate the deferred-actions registry once (sprint-4/23, T5) - the app's
    own lifespan does this too (``TestClient(app)`` triggers it), but a test
    that drives ``PendingActionService`` directly against a bare ``db`` session
    (no HTTP client) needs the registry populated regardless."""
    from app.deferred_actions.handlers import register_deferred_actions

    register_deferred_actions()
    yield


@pytest.fixture(scope="session")
def _session_factory_template():
    """Build the ``session_factory`` seeded database exactly ONCE per pytest
    session and capture it as bytes (see module docstring). Same seed path,
    same schema wiring as before - only WHEN it runs changed."""
    # The omnichannel module uses the `app_omnichannel` schema. SQLite has no
    # native schemas, so ATTACH an in-memory database as `omni` and translate
    # the module schema onto it - keeps module tables isolated from core (the
    # module's `statuses` must not collide with the core `statuses`, plan 07).
    from modules.autocount.db import AUTOCOUNT_SCHEMA, AutocountBase
    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase
    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase

    schema_translate_map = {
        # The module schema maps onto one attached in-memory db (distinct table
        # names; no collisions) - module tables stay isolated from core's.
        # autocount (sprint-4/13) maps onto the same attached db: its tables are
        # ``ac_``-prefixed, so they cannot collide with omnichannel's.
        # ideation (sprint-4/18) maps onto the same attached db too: its tables
        # are distinct names, and without the mapping ``bootstrap_modules``'s
        # ideation install raises "unknown database app_ideation" mid-suite.
        # meetings (sprint-5 S0) gets its OWN attached db - every module on disk
        # is globally installed by ``bootstrap_modules`` below, so a module whose
        # schema maps nowhere would fail its create_all and land in
        # ERRORED_MODULES for the whole suite.
        OMNI_SCHEMA: "omni",
        AUTOCOUNT_SCHEMA: "omni",
        "app_ideation": "omni",
        MEETINGS_SCHEMA: "meetings",
    }
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    OmniBase.metadata.create_all(bind=engine)
    AutocountBase.metadata.create_all(bind=engine)
    MeetingsBase.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )

    db = TestingSessionLocal()
    # Statuses + tenants (default + platform) + permission catalogs (core +
    # platform) + the platform operator - same seed path bootstrap_db runs.
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    seed_platform_admin(db)
    # Template engine (plan 07): platform-tier system templates - the suite's
    # email flows render through the engine like production.
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)

    # Default-tenant Admin role holding the core keys (module keys arrive via
    # the App-Store install below - plan 08 §5 grant model).
    admin_role = Role(
        tenant_id=DEFAULT_TENANT_ID,
        name="Admin",
        description="Full system access",
        is_system=True,
    )
    admin_role.permissions = tenant_admin_grant(db, DEFAULT_TENANT_ID)
    db.add(admin_role)
    db.flush()

    demo = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=ACTIVE_EMAIL,
        password=hash_password(ACTIVE_PASSWORD),
        name="Demo User",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    demo.roles = [admin_role]
    db.add(demo)
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email=INACTIVE_EMAIL,
            password=hash_password(INACTIVE_PASSWORD),
            name="Inactive User",
            status=UserStatus.INACTIVE.value,
        )
    )
    db.commit()

    # Module wiring, the real path (plan 08): catalog sync + global install,
    # then INSTALL omnichannel for the default tenant via the store service -
    # seeds the default workspace and grants the module keys to the Admin role.
    from app.module_loader import bootstrap_modules
    from app.services.app_store_service import AppStoreService

    bootstrap_modules(engine=engine, db=db)
    AppStoreService(db).install(DEFAULT_TENANT_ID, "omnichannel")
    # AutoCount ESB (sprint-4/13) - installed the same real store path, so its
    # permission keys land on the default tenant's Admin role like production.
    AppStoreService(db).install(DEFAULT_TENANT_ID, "autocount")
    db.close()

    blobs = _capture_sqlite_databases(engine, ("main", "omni", "meetings"))
    engine.dispose()
    return blobs, schema_translate_map


@pytest.fixture
def session_factory(_session_factory_template):
    blobs, schema_translate_map = _session_factory_template
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    _restore_sqlite_databases(engine, blobs)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )

    # Plan 34 (A7b) review round 1, S9 - the public web chat CORS preflight is
    # answered by an ASGI middleware, OUTSIDE FastAPI's dependency system, so
    # `get_db` cannot reach it (it would open the real DATABASE_URL). Same
    # seam and same reason as `routers/ws.py`'s handshake factory. The 60s
    # origin cache is cleared with it so one test's channel never answers for
    # the next test's. Process-global side effect - kept PER TEST, same as
    # before the template-DB split (module docstring).
    from modules.omnichannel.services import webchat_visitor_service as _webchat_visitor

    _webchat_visitor.set_preflight_session_factory(TestingSessionLocal)
    _webchat_visitor.reset_origins_cache()

    yield TestingSessionLocal

    _webchat_visitor.set_preflight_session_factory(None)
    _webchat_visitor.reset_origins_cache()
    engine.dispose()


@pytest.fixture(scope="session")
def _ideation_session_factory_template():
    """Build the ``ideation_session_factory`` seeded database exactly ONCE per
    pytest session and capture it as bytes (module docstring). Mirrors
    ``_session_factory_template`` but also schema-translates the ideation
    module's ``app_ideation`` schema onto its own attached in-memory db and
    installs ideation (which ``requires:["omnichannel"]``) for the default
    tenant via the App Store. Ideation tests get a session where the module
    is bootstrapped + installed exactly like production.
    """
    from modules.autocount.db import AUTOCOUNT_SCHEMA, AutocountBase
    from modules.ideation.db import IDEATION_SCHEMA, IdeationBase
    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase
    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase

    schema_translate_map = {
        # Each module schema maps onto its own attached in-memory db (distinct
        # table names; no collisions) - module tables stay isolated from core's.
        # autocount (sprint-4/13, merged from main) maps onto the `omni` db like
        # the core session_factory does so bootstrap_modules can install it here.
        OMNI_SCHEMA: "omni",
        AUTOCOUNT_SCHEMA: "omni",
        IDEATION_SCHEMA: "ideation",
        MEETINGS_SCHEMA: "meetings",
    }
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS ideation")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    OmniBase.metadata.create_all(bind=engine)
    AutocountBase.metadata.create_all(bind=engine)
    IdeationBase.metadata.create_all(bind=engine)
    MeetingsBase.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = TestingSessionLocal()
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    seed_platform_admin(db)
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)

    admin_role = Role(
        tenant_id=DEFAULT_TENANT_ID,
        name="Admin",
        description="Full system access",
        is_system=True,
    )
    admin_role.permissions = tenant_admin_grant(db, DEFAULT_TENANT_ID)
    db.add(admin_role)
    db.flush()

    demo = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=ACTIVE_EMAIL,
        password=hash_password(ACTIVE_PASSWORD),
        name="Demo User",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    demo.roles = [admin_role]
    db.add(demo)
    db.commit()

    # Real module wiring: catalog sync + global install for every module, then
    # install omnichannel (dependency) + ideation for the default tenant.
    from app.module_loader import bootstrap_modules
    from app.services.app_store_service import AppStoreService

    bootstrap_modules(engine=engine, db=db)
    store = AppStoreService(db)
    store.install(DEFAULT_TENANT_ID, "omnichannel")
    store.install(DEFAULT_TENANT_ID, "ideation")
    db.close()

    blobs = _capture_sqlite_databases(engine, ("main", "omni", "ideation", "meetings"))
    engine.dispose()
    return blobs, schema_translate_map


@pytest.fixture
def ideation_session_factory(_ideation_session_factory_template):
    blobs, schema_translate_map = _ideation_session_factory_template
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS ideation")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    _restore_sqlite_databases(engine, blobs)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    yield TestingSessionLocal

    engine.dispose()


_HTTP_RETRY_TEST_FILE_RE = re.compile(r"^test_(autocount_http_|s10_|s11_)")


@pytest.fixture(autouse=True)
def _no_real_sleep_in_autocount_http_tests(request, monkeypatch):
    """sprint-5/10 S1 review round 1 (should-fix 6) - AC-10-75's bounded
    retry ladder makes a genuine ``time.sleep`` call on a real timeout/5xx;
    several PRE-EXISTING ``test_autocount_http_*`` failure tests never
    monkeypatch it (only ``test_s10_http_retry.py`` did), so they now really
    sleep (~1-5s each) - noticeable machine-wide. Scoped by FILENAME, not a
    blanket suite-wide patch, so a test elsewhere that genuinely wants real
    timing (there are none today, but this stays narrow on principle)."""
    if _HTTP_RETRY_TEST_FILE_RE.match(request.node.fspath.basename):
        monkeypatch.setattr("time.sleep", lambda seconds: None)


# sprint-5/10 confirm-3 N1 - a PUBLIC-looking stub IP for every hostname the
# autocount test files construct a connection/task against
# (``hapi.sorento.cc.cd``, ``autocount.example.invalid``, etc). None of these
# resolve for real, and none is meant to - the egress guard
# (``app.services.url_guard``) falls back to "allow" under a resolution
# failure (``strict_dns=False``), so an unstubbed hostname already passed the
# guard, just by way of a REAL ``socket.getaddrinfo`` call reaching out
# first. 8.8.8.8 is definitively public under ``ipaddress`` (unlike, say, the
# TEST-NET-3 range, which the stdlib itself flags ``is_private``).
_PUBLIC_DNS_STUB_IP = "8.8.8.8"


def _stub_getaddrinfo(host, *_args, **_kwargs):
    import socket as _socket_module

    return [(_socket_module.AF_INET, _socket_module.SOCK_STREAM, 6, "", (_PUBLIC_DNS_STUB_IP, 0))]


@pytest.fixture(autouse=True)
def _stub_dns_in_autocount_http_tests(request, monkeypatch):
    """sprint-5/10 confirm-3 N1 - the SAME filename scope as the sleep-stub
    fixture above. ``app.services.url_guard.validate_public_https_url`` (called by
    ``modules.autocount.http_client.assert_autocount_base_url_deliverable``,
    the egress guard every open-REST request re-runs) resolves a non-IP-
    literal ``baseUrl`` host via ``socket.getaddrinfo`` before deciding
    public vs. private - a hostname test host (``hapi.sorento.cc.cd``, the
    connection-sizing suite's own ``BASE_URL``) hit a REAL resolver on every
    such test before this fixture existed. Every refusal test in this suite
    uses an IP LITERAL (``169.254.169.254``, ``127.0.0.1``, ``192.168.x.x``)
    so it never calls ``getaddrinfo`` at all and is UNAFFECTED by this stub -
    the guard's own ``ipaddress.ip_address`` branch runs first."""
    if _HTTP_RETRY_TEST_FILE_RE.match(request.node.fspath.basename):
        monkeypatch.setattr("socket.getaddrinfo", _stub_getaddrinfo)


_LIVE_NETWORK_BLOCK_FILE_RE = re.compile(r"^test_(autocount|s10_|s11_)")


class LiveNetworkAttempted(RuntimeError):
    """A test tried to send an ``httpx`` request over a REAL transport
    (``HTTPTransport``/``AsyncHTTPTransport``) instead of a stub. Raised by
    ``_block_live_network_in_autocount_tests`` below - stub the transport
    (``httpx.MockTransport``, or the ``get_http_transport`` FastAPI
    dependency override) instead."""


@pytest.fixture(autouse=True)
def _block_live_network_in_autocount_tests(request, monkeypatch):
    """sprint-5/10 confirm-4 - lane rule: no test under ``test_autocount*.py``
    / ``test_s10_*.py`` may touch the network (the live wrapper 403s the
    default UA and is slow; several individual s10 files already carried
    their own copy of this guard under the name ``_block_live_network``,
    first added 2026-09-20 after a coordinator finding that an earlier
    revision of a delivery-mode test made a real ~8-minute call to
    ``hapi.sorento.cc.cd``). This hoists the SAME guard so every file in the
    glob is covered whether or not it remembered its own copy - a file that
    already defines its own autouse ``_block_live_network`` fixture is left
    alone (this fixture no-ops for it) rather than double-patched.
    Raises the NAMED ``LiveNetworkAttempted`` (rather than a bare
    ``RuntimeError``) so a test can assert on it directly."""
    if not _LIVE_NETWORK_BLOCK_FILE_RE.match(request.node.fspath.basename):
        return
    if "_block_live_network" in request.fixturenames:
        return
    import httpx

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, req, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise LiveNetworkAttempted(
                f"blocked a LIVE network call to {req.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, req, *args, **kwargs)

    async def guarded_async_send(self, req, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise LiveNetworkAttempted(
                f"blocked a LIVE network call to {req.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, req, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def _meetings_session_factory_template():
    """Build the ``meetings_session_factory`` seeded database exactly ONCE per
    pytest session and capture it as bytes (module docstring). Mirrors
    ``_ideation_session_factory_template``: every module schema maps onto its
    own attached in-memory db, ``bootstrap_modules`` runs the real global
    install for all of them, and the App Store then installs ``meetings`` for
    the default tenant - so a meetings test gets the same wiring production
    has (permission grants included).
    """
    from modules.autocount.db import AUTOCOUNT_SCHEMA, AutocountBase
    from modules.ideation.db import IDEATION_SCHEMA, IdeationBase
    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase
    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase

    schema_translate_map = {
        # Every module on disk is globally installed by ``bootstrap_modules``
        # below, so every module schema needs somewhere to live here - one whose
        # schema maps nowhere lands in ERRORED_MODULES and pollutes the run.
        OMNI_SCHEMA: "omni",
        AUTOCOUNT_SCHEMA: "omni",
        IDEATION_SCHEMA: "ideation",
        MEETINGS_SCHEMA: "meetings",
    }
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS ideation")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    OmniBase.metadata.create_all(bind=engine)
    AutocountBase.metadata.create_all(bind=engine)
    IdeationBase.metadata.create_all(bind=engine)
    MeetingsBase.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = TestingSessionLocal()
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    seed_platform_admin(db)
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)

    admin_role = Role(
        tenant_id=DEFAULT_TENANT_ID,
        name="Admin",
        description="Full system access",
        is_system=True,
    )
    admin_role.permissions = tenant_admin_grant(db, DEFAULT_TENANT_ID)
    db.add(admin_role)
    db.flush()

    demo = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=ACTIVE_EMAIL,
        password=hash_password(ACTIVE_PASSWORD),
        name="Demo User",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    demo.roles = [admin_role]
    db.add(demo)
    db.commit()

    from app.module_loader import bootstrap_modules
    from app.services.app_store_service import AppStoreService

    bootstrap_modules(engine=engine, db=db)
    AppStoreService(db).install(DEFAULT_TENANT_ID, "meetings")
    db.close()

    blobs = _capture_sqlite_databases(engine, ("main", "omni", "ideation", "meetings"))
    engine.dispose()
    return blobs, schema_translate_map


@pytest.fixture
def meetings_session_factory(_meetings_session_factory_template):
    blobs, schema_translate_map = _meetings_session_factory_template
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=schema_translate_map)
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS ideation")
        conn.exec_driver_sql("ATTACH ':memory:' AS meetings")
        conn.commit()
    _restore_sqlite_databases(engine, blobs)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    yield TestingSessionLocal

    engine.dispose()

"""Storage migration engine (sprint-4/10 Slice 2) - AC-10-08..16.

Offline-deterministic: raw storage adapters are FAKED via an in-memory dict
(monkeypatching ``app.services.storage._adapter_for``), and the new-bucket TEST
probe is stubbed at the boto seam (``S3CompatibleAdapter._build_client``). The
fake adapter is also a SPY (records ``delete``/``fetch``) so we can assert the
source bucket is never destructively touched (AC-10-13).
"""
import pytest

from app.integrations.s3_provider import S3CompatibleAdapter
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_NEEDS_REVIEW,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import (
    CONNECTION_STATUS_ACTIVE,
    Connection,
)
from app.models.status import Status
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID, Tenant
from app.models.user import User, UserStatus
from app.repositories.connection_repository import ConnectionRepository
from app.secrets import encrypt_secret
from app.services import storage as storage_module
from app.services.storage import TenantStorage
from app.storage_migration import registry as reg
from app.storage_migration.registry import (
    StorageKeyLoc,
    register_storage_key_location,
)
from app.storage_migration.service import (
    STORAGE_MIGRATION,
    StorageMigrationService,
    run_storage_migration,
)
from tests.test_storage_providers import StubS3Client


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def only_avatar_location():
    """Register ONLY User.avatar_key so enumerate finds exactly our seeded keys."""
    saved = dict(reg._LOCATIONS)
    reg._LOCATIONS.clear()
    register_storage_key_location(
        StorageKeyLoc(model=User, column="avatar_key", tenant_column="tenant_id")
    )
    try:
        yield
    finally:
        reg._LOCATIONS.clear()
        reg._LOCATIONS.update(saved)


class FakeAdapter:
    """In-memory raw storage adapter + spy (records fetch/delete)."""

    def __init__(self):
        self.store: dict = {}
        self.fetched: list = []
        self.deleted: list = []

    def put_raw(self, raw, content, mime):
        self.store[raw] = (content, mime)

    def save(self, key_hint, content, mime):
        raw = f"{key_hint}-x"
        self.store[raw] = (content, mime)
        return raw

    def fetch(self, raw):
        self.fetched.append(raw)
        if raw not in self.store:
            raise FileNotFoundError(raw)
        return self.store[raw]

    def delete(self, raw):
        self.deleted.append(raw)
        self.store.pop(raw, None)


@pytest.fixture
def fakes(monkeypatch):
    """connection-id → FakeAdapter, wired into the storage adapter seam."""
    registry: dict = {}

    def fake_adapter_for(connection):
        return registry.setdefault(connection.id, FakeAdapter())

    monkeypatch.setattr(storage_module, "_adapter_for", fake_adapter_for)
    return registry


@pytest.fixture
def stub_probe(monkeypatch):
    """New-bucket TEST probe succeeds (head + round-trip) unless fail_head."""
    holder = {"client": StubS3Client()}
    monkeypatch.setattr(
        S3CompatibleAdapter, "_build_client", lambda self: holder["client"]
    )
    return holder


def _storage_conn(db, tenant_id=DEFAULT_TENANT_ID, *, active=True, name="A bucket"):
    row = Connection(
        tenant_id=tenant_id,
        provider="s3",
        type="storage",
        name=name,
        config_json={"bucket": "old", "region": "auto"},
        credentials_json=encrypt_secret({"accessKeyId": "ak", "secretAccessKey": "sk"}),
        status=CONNECTION_STATUS_ACTIVE,
        is_active=active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _point_avatar(db, tenant_id, keys):
    """Give N users in a tenant an avatar_key from `keys` (create if needed)."""
    users = (
        db.query(User)
        .filter(User.tenant_id == tenant_id)
        .order_by(User.email)
        .limit(len(keys))
        .all()
    )
    while len(users) < len(keys):
        u = User(
            tenant_id=tenant_id,
            email=f"asset{len(users)}-{tenant_id[:6]}@example.com",
            password="x",
            name="Asset user",
            status=UserStatus.ACTIVE.value,
        )
        db.add(u)
        db.flush()
        users.append(u)
    for user, key in zip(users, keys):
        user.avatar_key = key
    db.commit()
    return users


_NEW_BUCKET = {
    "provider": "s3",
    "name": "New bucket",
    "config": {"bucket": "new", "region": "auto"},
    "credentials": {"accessKeyId": "ak2", "secretAccessKey": "sk2"},
}


def _start(db, tenant_id=DEFAULT_TENANT_ID):
    return StorageMigrationService(db).start(
        tenant_id,
        "actor-1",
        provider=_NEW_BUCKET["provider"],
        name=_NEW_BUCKET["name"],
        new_config=_NEW_BUCKET["config"],
        new_credentials=_NEW_BUCKET["credentials"],
    )


# ── AC-10-08: is_active resolve filter vs key-resolve + relaxed index ──────────


def test_resolve_for_type_filters_is_active_but_key_resolve_ignores(db):
    repo = ConnectionRepository(db)
    a = _storage_conn(db)
    assert repo.resolve_for_type(DEFAULT_TENANT_ID, "storage").id == a.id

    repo.mark_active(a.id, False)
    db.commit()
    # No active storage → type-resolve misses; but resolve-BY-ID still finds A.
    assert repo.resolve_for_type(DEFAULT_TENANT_ID, "storage") is None
    assert repo.get_by_id(a.id).id == a.id


def test_inactive_a_and_active_b_coexist_under_relaxed_index(db):
    """The partial-unique index permits a retired A + an active B of one type."""
    a = _storage_conn(db, name="A")
    ConnectionRepository(db).mark_active(a.id, False)
    db.commit()
    b = _storage_conn(db, name="B")  # active - would violate the OLD index
    assert b.is_active is True
    assert a.is_active is False


# ── AC-10-09: start atomic (create-B + flip write-target + retire-A) ───────────


def test_start_creates_b_retires_a_and_writes_go_to_b(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    job = _start(db)

    db.refresh(a)
    assert a.is_active is False
    b_id = job.payload_json["toConnectionId"]
    b = ConnectionRepository(db).get_by_id(b_id)
    assert b.is_active is True and b.type == "storage"
    assert job.type == STORAGE_MIGRATION

    # Write-target flipped: a fresh save lands on B (conn:B:), never A.
    key = TenantStorage(db, DEFAULT_TENANT_ID).save("avatars/new", b"Z", "image/png")
    assert key.startswith(f"conn:{b_id}:")


def test_start_without_storage_connection_400(db, only_avatar_location, fakes, stub_probe):
    with pytest.raises(Exception) as exc:
        _start(db)
    assert getattr(exc.value, "status_code", None) == 400


def test_start_refuses_when_new_bucket_test_fails(db, only_avatar_location, fakes, monkeypatch):
    _storage_conn(db)
    monkeypatch.setattr(
        S3CompatibleAdapter, "_build_client", lambda self: StubS3Client(fail_head=True)
    )
    with pytest.raises(Exception) as exc:
        _start(db)
    assert getattr(exc.value, "status_code", None) == 422


# ── AC-10-10..12: copy + auto-cutover (clean) ─────────────────────────────────


# ── sprint-4/12 regression: worker self-registers storage-key locations ───────


def test_ensure_all_storage_locations_registers_module_keys(db):
    """Regression (sprint-4/12): a ``storage_migration`` job runs in the Celery
    worker, which never boots the FastAPI app - so module ``register_engine_
    entities`` (and core ``ensure_core_locations``) never ran there, ``_LOCATIONS``
    was EMPTY, ``enumerate_keys`` found 0 keys, and the migration finished "done"
    having copied/rewritten NOTHING (omnichannel ``conversation_messages.media_
    key`` stayed on the old connection id in prod). ``ensure_all_storage_
    locations`` registers core + every module location regardless of process.
    """
    from app.storage_migration.core_locations import ensure_all_storage_locations
    from app.storage_migration.registry import registered_scalar_columns

    # Snapshot AFTER a full populate - ``ensure_core_locations`` is ``lazy_once``,
    # so restoring a pre-populate snapshot would permanently drop core locations.
    ensure_all_storage_locations()
    saved = dict(reg._LOCATIONS)
    reg._LOCATIONS.clear()
    try:
        ensure_all_storage_locations()
        cols = registered_scalar_columns()
        # the exact columns that silently missed migration in production.
        assert ("conversation_messages", "media_key") in cols
        assert ("whatsapp_templates", "media_sample_key") in cols
    finally:
        reg._LOCATIONS.clear()
        reg._LOCATIONS.update(saved)


def test_migration_handler_self_registers_when_registry_empty(db, fakes, stub_probe):
    """End-to-end: even with ``_LOCATIONS`` cleared (a fresh worker), running the
    migration handler re-registers the module locations before enumerating - so
    the omnichannel media-key location is present, not silently skipped. With no
    keys seeded, the 0-keys guard HOLDS the job (needs_review) instead of a
    silent auto-cutover - the visible-not-silent behaviour the prod bug lacked."""
    from app.storage_migration.core_locations import ensure_all_storage_locations
    from app.storage_migration.registry import registered_scalar_columns

    ensure_all_storage_locations()  # populate before snapshot (lazy_once, see above)
    _storage_conn(db)  # A: an active storage connection to migrate from
    saved = dict(reg._LOCATIONS)
    reg._LOCATIONS.clear()  # simulate the worker process (nothing registered)
    try:
        job = _start(db)  # start() enqueues → eager run of the handler inline
        db.refresh(job)
        # The module location that was missing before the fix is now registered …
        assert ("conversation_messages", "media_key") in registered_scalar_columns()
        # … and an empty enumeration HOLDS for review (never a silent "done").
        assert job.status == JOB_NEEDS_REVIEW
        assert job.logs_json and any(
            "Enumerated" in e["message"] for e in job.logs_json
        )
    finally:
        reg._LOCATIONS.clear()
        reg._LOCATIONS.update(saved)


def test_zero_keys_holds_for_review_not_silent_done(db, only_avatar_location, fakes, stub_probe):
    """0-keys guard (sprint-4/12): a migration that enumerates nothing HOLDS at
    needs_review - the operator Completes it if bucket A is genuinely empty,
    rather than a "done" that migrated nothing (the prod silent no-op)."""
    _storage_conn(db)  # A exists, but no avatar_key points at it → 0 keys
    job = _start(db)
    db.refresh(job)
    assert job.status == JOB_NEEDS_REVIEW
    # Complete accepts the empty result and cuts over (nothing to rewrite).
    done = StorageMigrationService(db).complete(DEFAULT_TENANT_ID, job.id)
    assert done.status == JOB_DONE


def test_missing_declared_location_modules_detects_undercount(db):
    """Completeness detector (sprint-4/12 round 3): a module that DECLARES
    storage locations in its manifest but has fewer registered than declared is
    reported - the signal the migration uses to HOLD instead of stranding. Keyed
    by the ``module`` tag on registered locations, so it fires even when the
    module's models import failed entirely (nothing registered)."""
    from app.storage_migration.core_locations import (
        ensure_all_storage_locations,
        missing_declared_location_modules,
    )

    ensure_all_storage_locations()
    assert missing_declared_location_modules() == []  # fully registered

    saved = dict(reg._LOCATIONS)
    for sig in [s for s, loc in reg._LOCATIONS.items() if loc.module == "omnichannel"]:
        del reg._LOCATIONS[sig]  # simulate a stale worker that skipped omnichannel
    try:
        assert "omnichannel" in missing_declared_location_modules()
    finally:
        reg._LOCATIONS.clear()
        reg._LOCATIONS.update(saved)


def test_incomplete_registration_holds_without_cutover(db, fakes, stub_probe, monkeypatch):
    """THE data-safety guard (sprint-4/12 round 3). When a declaring module's
    locations fail to register (the prod stale-worker bug: omnichannel's
    ``media_key`` silently absent → "Registered 13 not 15"), the migration must
    HOLD at needs_review BEFORE cutover - never enumerate a subset, retire the
    source, and strand the rest. Proven by a CORE key that stays on A."""
    from app.storage_migration import core_locations

    ensure_all_storage_locations = core_locations.ensure_all_storage_locations
    ensure_all_storage_locations()  # populate core (lazy_once) before we clear omni

    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1"])  # a core key on A

    # Simulate the stale worker: omnichannel's declared locations fail to register
    # (its models import blows up in that process) - the handler's ensure_all
    # records the failure and leaves omnichannel undercounted.
    real = core_locations.register_module_declared_locations

    def flaky(manifest):
        if manifest["module_name"] == "omnichannel":
            raise ModuleNotFoundError("modules.omnichannel.models")
        return real(manifest)

    monkeypatch.setattr(core_locations, "register_module_declared_locations", flaky)
    for sig in [s for s, loc in reg._LOCATIONS.items() if loc.module == "omnichannel"]:
        del reg._LOCATIONS[sig]

    job = _start(db)
    db.refresh(job)

    assert job.status == JOB_NEEDS_REVIEW  # held, not "done"
    assert job.logs_json and any(
        "Incomplete storage-key registration" in e["message"] for e in job.logs_json
    )
    # CRITICAL: the core avatar key was NOT rewritten - no cutover, nothing
    # stranded. A still owns it (A is retired but serves by key).
    db.expire_all()
    key = db.query(User.avatar_key).filter(User.avatar_key.isnot(None)).scalar()
    assert key == f"conn:{a.id}:raw1"


def test_clean_migration_copies_and_cutovers(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    a_fake.store["raw2"] = (b"two", "image/webp")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    db.refresh(job)
    assert job.status == JOB_DONE
    assert job.result_json["copied"] == 2 and job.result_json["failed"] == 0

    b_id = job.payload_json["toConnectionId"]
    b_fake = fakes[b_id]
    assert set(b_fake.store) == {"raw1", "raw2"}

    db.expire_all()
    remaining = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None)).all()}
    assert remaining == {f"conn:{b_id}:raw1", f"conn:{b_id}:raw2"}


def test_copy_idempotent_skips_blobs_present_in_b(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    a_fake.store["raw2"] = (b"two", "image/png")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    # Pre-place raw1 in B (a prior run / resume): the copy loop must SKIP it -
    # never re-fetch from A. Build B + a running job manually to control state.
    b = _storage_conn(db, name="B", active=False)
    b_fake = fakes.setdefault(b.id, FakeAdapter())
    b_fake.store["raw1"] = (b"one", "image/png")
    ConnectionRepository(db).mark_active(a.id, False)
    ConnectionRepository(db).mark_active(b.id, True)
    db.commit()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=STORAGE_MIGRATION, status=JOB_RUNNING,
        payload_json={"fromConnectionId": a.id, "toConnectionId": b.id},
    )
    db.add(job)
    db.commit()

    run_storage_migration(db, job)
    db.refresh(job)
    assert job.status == JOB_DONE
    assert "raw1" not in a_fake.fetched  # skipped - already in B
    assert "raw2" in a_fake.fetched


def test_continue_on_bad_blob_holds_needs_review(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 intentionally missing
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    db.refresh(job)
    assert job.status == JOB_NEEDS_REVIEW
    assert job.result_json["failed"] == 1
    assert job.result_json["failures"][0]["key"] == f"conn:{a.id}:raw2"
    assert job.finished_at is None  # non-terminal - assets keep serving

    # No cutover yet - BOTH rows still point at A.
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None)).all()}
    assert vals == {f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"}


# ── AC-10-11/12: complete = partial rewrite of only-copied, value-checked ──────


def test_complete_rewrites_only_copied_keys(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 missing → failure
    # Three explicit rows: raw1 (copies), raw2 (fails), and one already on B.
    b_placeholder = "conn:someB:already"
    rows = []
    for i, key in enumerate([f"conn:{a.id}:raw1", f"conn:{a.id}:raw2", b_placeholder]):
        u = User(tenant_id=DEFAULT_TENANT_ID, email=f"cmp{i}@example.com", password="x",
                 name=f"cmp{i}", status=UserStatus.ACTIVE.value, avatar_key=key)
        db.add(u)
        rows.append(u)
    db.commit()

    job = _start(db)
    b_id = job.payload_json["toConnectionId"]
    StorageMigrationService(db).complete(DEFAULT_TENANT_ID, job.id)

    db.expire_all()
    by_email = {u.email: u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None))}
    # only raw1 (copied) rewritten; raw2 (failed) stays on A; pre-B row untouched.
    assert f"conn:{b_id}:raw1" in by_email.values()
    assert f"conn:{a.id}:raw2" in by_email.values()
    assert b_placeholder in by_email.values()


# ── AC-10-13: retire A never touches the bucket ───────────────────────────────


def test_source_bucket_never_deleted(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1"])

    _start(db)
    assert a_fake.deleted == []  # zero destructive calls on the source adapter
    db.refresh(a)
    assert a.is_active is False  # retired, kept for audit


# ── AC-10-14: job control (one-active, abort, retry, connection lock) ──────────


def test_one_active_migration_per_connection_409(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=STORAGE_MIGRATION, status=JOB_RUNNING,
            payload_json={"fromConnectionId": a.id, "toConnectionId": "other"},
        )
    )
    db.commit()
    with pytest.raises(Exception) as exc:
        _start(db)
    assert getattr(exc.value, "status_code", None) == 409


def test_abort_restores_a_and_keeps_b(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 missing → needs_review
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    b_id = job.payload_json["toConnectionId"]
    assert job.status == JOB_NEEDS_REVIEW

    StorageMigrationService(db).abort(DEFAULT_TENANT_ID, job.id)
    db.refresh(job)
    db.refresh(a)
    b = ConnectionRepository(db).get_by_id(b_id)
    assert job.status == JOB_ABORTED
    assert a.is_active is True and b.is_active is False  # A restored, B kept-inactive
    # No rewrite happened.
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None))}
    assert vals == {f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"}
    # Write-target back to A.
    assert ConnectionRepository(db).resolve_for_type(DEFAULT_TENANT_ID, "storage").id == a.id


def test_abort_mid_run_prevents_cutover(db, only_avatar_location, fakes, stub_probe):
    """Cooperative cancel (real Celery path): a job flipped to ABORTED before the
    handler reaches cutover must NOT rewrite keys nor overwrite the aborted status
    (AC-10-14). Reviewer should-fix #1."""
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    a_fake.store["raw2"] = (b"two", "image/png")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    b = _storage_conn(db, name="B", active=False)
    fakes.setdefault(b.id, FakeAdapter())
    ConnectionRepository(db).mark_active(a.id, False)
    ConnectionRepository(db).mark_active(b.id, True)
    # Job already ABORTED (a concurrent abort committed it) - the handler's
    # pre-cutover status re-read must bail.
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=STORAGE_MIGRATION, status=JOB_ABORTED,
        payload_json={"fromConnectionId": a.id, "toConnectionId": b.id},
    )
    db.add(job)
    db.commit()

    run_storage_migration(db, job)

    db.refresh(job)
    assert job.status == JOB_ABORTED  # never overwritten to DONE
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None))}
    assert vals == {f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"}  # NO rewrite to conn:B:


def test_retry_reruns_and_cutovers_when_clean(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 missing at first
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    assert job.status == JOB_NEEDS_REVIEW

    # Fix the source, then retry → clean → auto-cutover.
    a_fake.store["raw2"] = (b"two", "image/png")
    StorageMigrationService(db).retry(DEFAULT_TENANT_ID, job.id)
    db.refresh(job)
    b_id = job.payload_json["toConnectionId"]
    assert job.status == JOB_DONE and job.result_json["failed"] == 0
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None))}
    assert vals == {f"conn:{b_id}:raw1", f"conn:{b_id}:raw2"}


def test_connection_locked_during_migration(db, only_avatar_location, fakes):
    from app.schemas.integration import ConnectionUpdateRequest
    from app.services.integration_service import IntegrationService

    a = _storage_conn(db)
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=STORAGE_MIGRATION, status=JOB_RUNNING,
            payload_json={"fromConnectionId": a.id, "toConnectionId": "b"},
        )
    )
    db.commit()
    with pytest.raises(Exception) as exc:
        IntegrationService(db).update(
            DEFAULT_TENANT_ID, a.id, ConnectionUpdateRequest(name="renamed")
        )
    assert getattr(exc.value, "status_code", None) == 409


# ── AC-10-15: platform connection sweeps ALL fallback tenants ──────────────────


def test_platform_migration_sweeps_other_tenants_keys(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db, PLATFORM_TENANT_ID)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["rawX"] = (b"x", "image/png")

    # A SECOND tenant fell back to the platform bucket - its user row carries a
    # conn:<platform A>: key. Enumeration is connection-scoped → sweeps it.
    status_id = db.query(Status.id).filter(Status.entity_type == "tenant").first()[0]
    other = Tenant(name="Other Co", slug="other-co-mig", status_id=status_id)
    db.add(other)
    db.commit()
    _point_avatar(db, other.id, [f"conn:{a.id}:rawX"])

    job = _start(db, PLATFORM_TENANT_ID)
    db.refresh(job)
    assert job.status == JOB_DONE
    b_id = job.payload_json["toConnectionId"]
    db.expire_all()
    swept = (
        db.query(User)
        .filter(User.tenant_id == other.id, User.avatar_key.isnot(None))
        .first()
    )
    assert swept.avatar_key == f"conn:{b_id}:rawX"  # cross-tenant sweep, no special code


# ── AC-10-16: permission + grant sweep + gate ─────────────────────────────────


def test_migrate_permission_in_tenant_admin_grant(db):
    from app.seed import tenant_admin_grant

    keys = {p.key for p in tenant_admin_grant(db, DEFAULT_TENANT_ID)}
    assert "integrations.migrate_storage" in keys


def test_admin_role_holds_migrate_storage(db):
    from app.models.role import Role

    admin = (
        db.query(Role)
        .filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin")
        .first()
    )
    assert "integrations.migrate_storage" in {p.key for p in admin.permissions}


def test_start_endpoint_requires_permission(client, session_factory):
    from app.models.role import Role
    from app.security import hash_password

    # A user WITHOUT the migrate perm gets 403 from the endpoint gate.
    setup = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="ReadOnly", description="ro", is_system=False)
    setup.add(role)
    setup.flush()
    role.permissions = [p for p in role.permissions]  # empty
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email="noperm-mig@example.com",
        password=hash_password("Passw0rd!x"), name="No Perm",
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    setup.add(user)
    setup.commit()
    setup.close()

    res = client.post("/auth/login", json={"email": "noperm-mig@example.com", "password": "Passw0rd!x"})
    assert res.status_code == 200
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    out = client.post("/storage/migrations", json=_NEW_BUCKET, headers=headers)
    assert out.status_code == 403


def test_start_endpoint_allows_admin_perm(client):
    # Demo Admin HOLDS the perm - the gate passes; with no storage connection
    # the endpoint reaches the service and returns 400 (not 403).
    res = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    out = client.post("/storage/migrations", json=_NEW_BUCKET, headers=headers)
    assert out.status_code == 400  # perm passed, no bucket to migrate from

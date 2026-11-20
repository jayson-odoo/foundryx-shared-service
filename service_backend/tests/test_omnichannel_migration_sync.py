"""Lane SS-MIGRATION-SYNC (plan sprint-5/52) - RED tests, part 1: the sync
record + lifecycle (AC-SYNC-01..06) and the public webhook (AC-SYNC-30..33).
Ticks / source-wins / errors live in `test_omnichannel_migration_sync_ticks.py`.

Written BEFORE any implementation: they target the interfaces plan 52 names
(`MigrationSync` / `MigrationSyncHint` models, `/omnichannel/migration/syncs`,
`POST /omnichannel/migration-hooks/{id}/{secret}`).

Every test seeds its own data chain (workspace + connection + channel + a real
DONE run job through `run_migration_job`); nothing borrows seeded rows. The
respond.io side is `FakeRespondIo` over an httpx.MockTransport - no network.
"""
import math

import pytest
from datetime import timedelta

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_FAILED, JOB_DONE

from tests.test_omnichannel_migration_sync_support import (
    close_all_worlds,
    SYNCS,
    add_done_job,
    create_sync,
    get_sync,
    hint_ids,
    new_world,
    post_hint,
    set_sync,
    start_sync,
    sync_models,
    sync_row,
    utcnow,
    webhook_path,
)
from tests.test_omnichannel_respondio_migration_jobs import _auth


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


def _world_with_run(session_factory, monkeypatch, *, rps="1000", contacts=1):
    w = new_world(session_factory, monkeypatch, rps=rps)
    for i in range(contacts):
        cid = 910001 + i
        w.fake.add_contact(cid, first=f"Syn{i}")
        w.fake.add_message(cid, 1, text="first")
    w.run_migration()
    w.db.commit()
    w.fake.clear_calls()
    return w


def _secret_of(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[1]


def _make_reader(session_factory, email="sync-reader@example.com"):
    from app.models import Permission, Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    read_perm = db.query(Permission).filter(Permission.key == "omnichannel_migration.read").first()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Sync Reader")
    role.permissions = [read_perm]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("Password123!"),
        name="Reader", status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()
    return email, "Password123!"


def _make_other_tenant(session_factory, slug="other-sync", email="admin-other-sync@example.com"):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Sync Tenant", slug=slug, admin_email=email, admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    tenant_id = tenant.id
    db.close()
    return tenant_id, email, "Password123!", slug


# ═══════════════════════════════════════════════════════════════════════════
# Slice 1 - the sync record and its lifecycle
# ═══════════════════════════════════════════════════════════════════════════


def test_sync_01_create_from_done_run(client, session_factory, monkeypatch):
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)

    res = create_sync(client, h, w.ws.id)
    assert res.status_code == 201, res.text
    item = res.json()
    assert item["status"] == "active"
    assert item["workspaceId"] == w.ws.id
    assert item["intervalMinutes"] == 15
    assert item["fullSweepHours"] == 6
    assert item["sourceJobId"] == w.job.id, "the mapping is taken from the finished run"
    assert item["id"]

    # A webhook secret exists, lives in the URL path, and is stored encrypted.
    path = webhook_path(client, h, item["id"])
    assert path.startswith(f"/omnichannel/migration-hooks/{item['id']}/")
    secret = _secret_of(path)
    assert len(secret) >= 32
    row = sync_row(w.db, item["id"])
    assert row.tenant_id == DEFAULT_TENANT_ID and row.workspace_id == w.ws.id
    assert row.created_by_user_id, "the creator is recorded (token-rejected email goes to them)"
    assert row.webhook_secret_enc and secret not in row.webhook_secret_enc, "secret is Fernet-encrypted at rest"


def test_sync_02_no_finished_real_api_run_is_409_and_stores_nothing(client, session_factory, monkeypatch):
    w = new_world(session_factory, monkeypatch)
    h = _auth(client)
    MigrationSync, _ = sync_models()

    def expect_refused(label):
        res = create_sync(client, h, w.ws.id)
        assert res.status_code == 409, f"{label}: {res.text}"
        assert res.json()["detail"]["reason"] == "no_finished_migration", label
        w.db.expire_all()
        assert w.db.query(MigrationSync).filter(MigrationSync.tenant_id == DEFAULT_TENANT_ID).count() == 0, label

    expect_refused("no migration at all")

    add_done_job(w.db, w.ws, w.conn, mode="dry_run", result={"report": {"entities": {"contacts": {"fetched": 5}}}})
    expect_refused("only a dry run")

    add_done_job(w.db, w.ws, None, mode="run", source="csv")
    expect_refused("only a CSV run")

    add_done_job(w.db, w.ws, w.conn, mode="run", source="api", status=JOB_FAILED)
    expect_refused("the only real run failed")

    # Control: a finished real API run makes the very same call succeed.
    add_done_job(w.db, w.ws, w.conn, mode="run", source="api", status=JOB_DONE, channel_target=w.channel.id)
    ok = create_sync(client, h, w.ws.id)
    assert ok.status_code == 201, ok.text


def test_sync_03_exists_409_and_stopped_row_is_reactivated(client, session_factory, monkeypatch):
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)
    first = start_sync(client, w.ws.id, h)
    sync_id = first["id"]
    old_secret = _secret_of(webhook_path(client, h, sync_id))

    dup = create_sync(client, h, w.ws.id)
    assert dup.status_code == 409
    assert dup.json()["detail"]["reason"] == "sync_exists"

    assert client.post(f"{SYNCS}/{sync_id}/pause", headers=h).status_code == 200
    dup_paused = create_sync(client, h, w.ws.id)
    assert dup_paused.status_code == 409
    assert dup_paused.json()["detail"]["reason"] == "sync_exists"

    # Stopped: create re-activates the SAME row (new secret, totals kept).
    totals = {"contactsCreated": 3, "contactsUpdated": 1, "messagesCreated": 7, "messagesSkipped": 2, "errors": 0}
    set_sync(w.db, sync_id, status="stopped", stopped_at=utcnow(), totals_json=totals)
    again = create_sync(client, h, w.ws.id)
    assert again.status_code == 201, again.text
    item = again.json()
    assert item["id"] == sync_id
    assert item["status"] == "active"
    assert item["totals"]["messagesCreated"] == 7
    assert _secret_of(webhook_path(client, h, sync_id)) != old_secret

    MigrationSync, _ = sync_models()
    w.db.expire_all()
    assert w.db.query(MigrationSync).filter(MigrationSync.workspace_id == w.ws.id).count() == 1


def test_sync_04_tenant_scope_and_read_only_user(client, session_factory, monkeypatch):
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)
    item = start_sync(client, w.ws.id, h)
    sync_id = item["id"]

    # Another tenant: 404 on every route that takes the id, never the row.
    other_tenant_id, email2, pw2, slug2 = _make_other_tenant(session_factory)
    h2 = _auth(client, email=email2, password=pw2, tenant_slug=slug2)
    assert client.get(f"{SYNCS}/{sync_id}", headers=h2).status_code == 404
    for action in ("run-now", "pause", "resume", "stop"):
        assert client.post(f"{SYNCS}/{sync_id}/{action}", headers=h2).status_code == 404, action
    assert client.get(f"{SYNCS}/{sync_id}/webhook", headers=h2).status_code == 404
    assert client.post(f"{SYNCS}/{sync_id}/webhook/rotate", headers=h2).status_code == 404
    listed = client.get(SYNCS, params={"workspaceId": w.ws.id}, headers=h2)
    assert listed.status_code in (200, 404)
    if listed.status_code == 200:
        assert listed.json() is None
    foreign_create = create_sync(client, h2, w.ws.id)
    assert foreign_create.status_code != 201
    MigrationSync, _ = sync_models()
    w.db.expire_all()
    assert w.db.query(MigrationSync).filter(MigrationSync.tenant_id == other_tenant_id).count() == 0
    # The owner's sync is untouched by all of the above.
    assert get_sync(client, h, sync_id)["status"] == "active"

    # A read-only user can GET but every write (and the webhook URL) is 403.
    email, pw = _make_reader(session_factory)
    hr = _auth(client, email=email, password=pw)
    got = client.get(f"{SYNCS}/{sync_id}", headers=hr)
    assert got.status_code == 200 and got.json()["id"] == sync_id
    listed_r = client.get(SYNCS, params={"workspaceId": w.ws.id}, headers=hr)
    assert listed_r.status_code == 200 and listed_r.json()["id"] == sync_id
    assert create_sync(client, hr, w.ws.id).status_code == 403
    for action in ("run-now", "pause", "resume", "stop", "webhook/rotate"):
        assert client.post(f"{SYNCS}/{sync_id}/{action}", headers=hr).status_code == 403, action
    assert client.get(f"{SYNCS}/{sync_id}/webhook", headers=hr).status_code == 403
    assert get_sync(client, h, sync_id)["status"] == "active", "nothing the reader tried changed the sync"


def test_sync_05_item_hides_secret_and_webhook_url_rotates(client, session_factory, monkeypatch):
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)

    empty = client.get(SYNCS, params={"workspaceId": w.ws.id}, headers=h)
    assert empty.status_code == 200
    assert empty.json() is None, "no sync yet -> null"

    item = start_sync(client, w.ws.id, h)
    sync_id = item["id"]
    old_path = webhook_path(client, h, sync_id)
    old_secret = _secret_of(old_path)

    listed = client.get(SYNCS, params={"workspaceId": w.ws.id}, headers=h)
    assert listed.status_code == 200 and listed.json()["id"] == sync_id
    for res in (listed, client.get(f"{SYNCS}/{sync_id}", headers=h), client.post(f"{SYNCS}/{sync_id}/run-now", headers=h)):
        body = res.json()
        assert old_secret not in res.text
        assert not any("secret" in k.lower() or "webhook" in k.lower() or k.lower() == "url" for k in body), body.keys()

    # The old URL is accepted before the rotation (control) ...
    assert post_hint(client, old_path, {"contact": {"id": 4242}}).status_code == 200

    rotated = client.post(f"{SYNCS}/{sync_id}/webhook/rotate", headers=h)
    assert rotated.status_code == 200, rotated.text
    new_url = rotated.json()["url"]
    assert _secret_of(new_url) != old_secret
    assert new_url == client.get(f"{SYNCS}/{sync_id}/webhook", headers=h).json()["url"]

    # ... and 404s afterwards, while the new one works.
    assert post_hint(client, old_path, {"contact": {"id": 4243}}).status_code == 404
    new_path = webhook_path(client, h, sync_id)
    assert post_hint(client, new_path, {"contact": {"id": 4244}}).status_code == 200
    assert "4243" not in hint_ids(w.db, sync_id)


def test_sync_05_webhook_url_uses_public_base_url(client, session_factory, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://ss.example.test")
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)
    item = start_sync(client, w.ws.id, h)
    url = client.get(f"{SYNCS}/{item['id']}/webhook", headers=h).json()["url"]
    assert url.startswith(f"https://ss.example.test/omnichannel/migration-hooks/{item['id']}/")


def test_sync_06_contact_count_and_estimate_dry_run_then_tick(client, session_factory, monkeypatch):
    from tests.test_omnichannel_migration_sync_support import make_due, run_due_syncs

    w = _world_with_run(session_factory, monkeypatch, rps="2", contacts=3)
    # The latest dry run measured 130 contacts (the real run above saw 3).
    add_done_job(
        w.db, w.ws, w.conn, mode="dry_run",
        result={"report": {"entities": {"contacts": {"fetched": 130}}}},
        finished_at=utcnow() - timedelta(minutes=5),
    )
    h = _auth(client)
    item = start_sync(client, w.ws.id, h)
    assert item["sourceContactCount"] == 130
    assert item["estimatedFullSweepMinutes"] == math.ceil(130 * 3 / 2 / 60) == 4

    # After a tick the count comes from that tick's contact walk (3 contacts).
    make_due(w.db, item["id"])
    run_due_syncs(w.db)
    after = get_sync(client, h, item["id"])
    assert after["sourceContactCount"] == 3
    assert after["estimatedFullSweepMinutes"] == math.ceil(3 * 3 / 2 / 60) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Slice 4 - the public webhook (a hint, never a payload)
# ═══════════════════════════════════════════════════════════════════════════


def _hooked(client, session_factory, monkeypatch):
    w = _world_with_run(session_factory, monkeypatch)
    h = _auth(client)
    item = start_sync(client, w.ws.id, h)
    w.fake.clear_calls()
    return w, h, item["id"], webhook_path(client, h, item["id"])


def test_sync_30_webhook_stores_one_hint_and_calls_nothing(client, session_factory, monkeypatch):
    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)

    shapes = [
        {"contact": {"id": 120001}},
        {"contactId": 120002},
        {"data": {"contact": {"id": 120003}}},
        {"contact": {"id": "120004"}},
    ]
    for body in shapes:
        res = post_hint(client, path, body)  # NO auth header: the URL secret is the capability
        assert res.status_code == 200, (body, res.text)
        assert res.json() == {"ok": True}
    assert hint_ids(w.db, sync_id) == ["120001", "120002", "120003", "120004"]
    assert w.fake.calls == [], "the request path never calls respond.io"


def test_sync_31_wrong_secret_unknown_stopped_inactive_module_are_uniform_404(client, session_factory, monkeypatch):
    from app.services.app_store_service import AppStoreService

    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)
    secret = _secret_of(path)
    base = f"/omnichannel/migration-hooks/{sync_id}"

    # Control: the right URL is accepted and stores a hint.
    assert post_hint(client, path, {"contact": {"id": 130001}}).status_code == 200
    assert hint_ids(w.db, sync_id) == ["130001"]

    def assert_uniform_404(url, label):
        res = post_hint(client, url, {"contact": {"id": 130999}})
        assert res.status_code == 404, label
        assert res.json() == {"detail": "Not Found"}, label

    assert_uniform_404(f"{base}/{'x' * len(secret)}", "wrong secret")
    assert_uniform_404(f"{base}/{secret[:-1]}", "truncated secret")
    assert_uniform_404(f"/omnichannel/migration-hooks/00000000-0000-0000-0000-000000000000/{secret}", "unknown sync id")

    # Paused and stopping syncs still accept hints (the next tick consumes them).
    set_sync(w.db, sync_id, status="paused")
    assert post_hint(client, path, {"contact": {"id": 130002}}).status_code == 200
    set_sync(w.db, sync_id, status="stopping")
    assert post_hint(client, path, {"contact": {"id": 130003}}).status_code == 200

    set_sync(w.db, sync_id, status="stopped", stopped_at=utcnow())
    assert_uniform_404(path, "stopped sync")

    set_sync(w.db, sync_id, status="active", stopped_at=None)
    assert post_hint(client, path, {"contact": {"id": 130004}}).status_code == 200
    AppStoreService(w.db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    w.db.commit()
    assert_uniform_404(path, "omnichannel not active for the tenant")

    assert hint_ids(w.db, sync_id) == ["130001", "130002", "130003", "130004"], "no 404 stored anything"


def test_sync_31_secret_compared_in_constant_time():
    import inspect

    src = inspect.getsource(sync_service_module())
    assert "compare_digest" in src, "the webhook secret must be compared with hmac.compare_digest"


def sync_service_module():
    from tests.test_omnichannel_migration_sync_support import sync_service_module as _m

    return _m()


def test_sync_32_unusable_bodies_never_500_and_store_nothing(client, session_factory, monkeypatch):
    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)
    json_h = {"content-type": "application/json"}

    # Control first: a usable body is stored.
    assert post_hint(client, path, {"contact": {"id": 140001}}).status_code == 200
    assert hint_ids(w.db, sync_id) == ["140001"]

    unusable = [
        client.post(path, content=b"not json at all", headers=json_h),
        client.post(path, content=b"", headers=json_h),
        client.post(path, json={"foo": "bar"}),
        client.post(path, json={"contact": {"id": "abc"}}),
        client.post(path, json={"contact": {"id": ""}}),
        client.post(path, json={"contact": {"id": "9" * 21}}),
        client.post(path, json=[1, 2, 3]),
        client.post(path, json={"contact": "7"}),
    ]
    for res in unusable:
        assert res.status_code == 204, res.text
    assert hint_ids(w.db, sync_id) == ["140001"]

    oversize = b'{"contact":{"id":140002},"pad":"' + b"x" * (64 * 1024 + 10) + b'"}'
    big = client.post(path, content=oversize, headers=json_h)
    assert big.status_code == 413
    assert hint_ids(w.db, sync_id) == ["140001"]


def test_sync_32_hints_are_deduped_per_contact(client, session_factory, monkeypatch):
    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)
    for _ in range(3):
        assert post_hint(client, path, {"contact": {"id": 150001}}).status_code == 200
    assert post_hint(client, path, {"contactId": "150001"}).status_code == 200
    assert post_hint(client, path, {"contact": {"id": 150002}}).status_code == 200
    assert hint_ids(w.db, sync_id) == ["150001", "150002"]


def test_sync_32_pending_hints_capped_at_5000(client, session_factory, monkeypatch):
    _, MigrationSyncHint = sync_models()
    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)
    w.db.bulk_insert_mappings(
        MigrationSyncHint,
        [
            {"tenant_id": DEFAULT_TENANT_ID, "sync_id": sync_id, "external_contact_id": str(200000 + i),
             "created_at": utcnow()}
            for i in range(4999)
        ],
    )
    w.db.commit()
    assert len(hint_ids(w.db, sync_id)) == 4999

    # 4999 pending -> the 5000th is stored (control) ...
    assert post_hint(client, path, {"contact": {"id": 150100}}).status_code == 200
    assert len(hint_ids(w.db, sync_id)) == 5000
    # ... the next is dropped (never a 500; the full sweep covers it).
    over = post_hint(client, path, {"contact": {"id": 150101}})
    assert over.status_code in (200, 204), over.text
    ids = hint_ids(w.db, sync_id)
    assert len(ids) == 5000 and "150101" not in ids


def test_sync_33_payload_is_never_written_only_the_contact_id(client, session_factory, monkeypatch):
    from modules.omnichannel.models import ConversationMessage
    from tests.test_omnichannel_migration_sync_support import make_due, run_due_syncs

    w, h, sync_id, path = _hooked(client, session_factory, monkeypatch)
    marker = "FORGED-PAYLOAD-MARKER-77"
    body = {
        "contact": {"id": 910001, "firstName": marker},
        "message": {"messageId": 99, "traffic": "incoming", "message": {"type": "text", "text": marker}},
    }
    before = w.db.query(ConversationMessage).filter(ConversationMessage.tenant_id == DEFAULT_TENANT_ID).count()
    assert post_hint(client, path, body).status_code == 200

    _, MigrationSyncHint = sync_models()
    w.db.expire_all()
    rows = w.db.query(MigrationSyncHint).filter(MigrationSyncHint.sync_id == sync_id).all()
    assert [r.external_contact_id for r in rows] == ["910001"]
    for r in rows:
        dumped = " ".join(str(getattr(r, c.name)) for c in r.__table__.columns)
        assert marker not in dumped
    assert w.db.query(ConversationMessage).filter(ConversationMessage.tenant_id == DEFAULT_TENANT_ID).count() == before

    # The tick re-reads the contact from the respond.io API; what lands is the
    # API's message, never the forged one.
    w.fake.add_message(910001, 2, text="the real message from the API")
    set_sync(w.db, sync_id, next_sync_at=utcnow() + timedelta(minutes=10))
    run_due_syncs(w.db)
    w.db.expire_all()
    bodies = [m.body for m in w.db.query(ConversationMessage).filter(ConversationMessage.tenant_id == DEFAULT_TENANT_ID).all()]
    assert "the real message from the API" in bodies
    assert not any(marker in (b or "") for b in bodies)
    c = w.contact_by_cid(910001)
    assert marker not in (c.first_name or "")

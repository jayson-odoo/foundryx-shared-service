"""Sprint-5/10 S4 - operator KEY routes + revoke: AC-10-36, 37 (keys half).

Wire shapes = the shipped FE contract (coordinator ruling, carried over from
S3): `service_frontend/types/autocount.ts` (`AutocountPullApiKey`,
`AutocountPullApiKeyCreateInput`, `AutocountPullApiKeyIssued`) and
`service_frontend/services/autocount-service.real.ts` (`listPullKeys` GET
`/autocount/pull/keys` -> a BARE ARRAY, not the house `{data,total,page}`
envelope; `issuePullKey` POST same path; `revokePullKey` POST
`/autocount/pull/keys/{id}/revoke`). Read-only on `service_frontend/`.

AMBIGUITY, flagged rather than silently resolved (see the final report):
plan section 2.6 says Revoke goes through the CORE deferred-action grace
window "never a hand-rolled confirm", which is a DIFFERENT shape
(`PendingActionCreateResponse {id, commitAt, windowSeconds}`) than the
FE's own `revokePullKey` (a synchronous `POST .../revoke` returning the
updated `AutocountPullApiKey` directly). The closest precedent in this
module, "Re-push all" (`deferred_actions.py`), ships BOTH a direct
route AND a deferred-action registration wired to the SAME service method
(its own docstring: "the API-path route stays... this module wires the
SAME method into the deferred-actions engine as a SECOND entry point") - so
this file tests BOTH paths, assuming the coder follows that established
dual-entry-point pattern rather than picking one.

RED before the coder: none of these routes/registrations exist yet.

ASSUMED NAMES:

* Router: `GET/POST /autocount/pull/keys`, `POST
  /autocount/pull/keys/{id}/revoke`, ALL gated `autocount.pull.manage`
  (AC-10-37's own parenthetical covers all three). Same router file/prefix
  as S3's `routers/pull.py` (`/autocount/pull`).
* Schemas mirror `AutocountPullApiKey`/`...CreateInput`/`...Issued` exactly:
  `id, name, companyIds, keyPrefix, createdAt, lastUsedAt, revokedAt` /
  `name, companyIds` / `{key, plaintext}`.
* Permissions `autocount.pull.read` + `autocount.pull.manage` added to
  `modules/autocount/permissions/permissions.csv` (AC-10-36) - verified
  against core for collisions; `update_tenant` re-runs the tenant Admin
  grant sweep so an ALREADY-PROVISIONED tenant's Admin gets both keys.
* Deferred action (plan §2.6): key `"autocount_pull_api_key.revoke"`,
  entity type `"autocount_pull_api_key"` - pinned to the shipped FE contract
  (`service_frontend/app/(protected)/autocount/pull/components/
  use-pull-list-config.tsx:290`, `lib/deferred-verb.ts`'s `ENTITY_NOUNS`
  row), consistent with the table name `ac_pull_api_key` - permission
  `"autocount.pull.manage"`,
  registered in `modules/autocount/deferred_actions.py` beside
  `autocount_etl_task.repush`, executor calling
  `PullKeyService.revoke(tenant_id, entity_id)`.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.deferred_actions.registry import deferred_action_for
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.pending_action import PendingAction
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from sqlalchemy.sql import func

OTHER_TENANT = "tenant-other-s10-s4-key-routes"
ACTION_KEY = "autocount_pull_api_key.revoke"
ENTITY_TYPE = "autocount_pull_api_key"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    `test_s10_s3_delivery_mode.py`'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    import httpx

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _limited_user(db, keys, email) -> None:
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in PermissionRepository(db).list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("limited1234"),
        name="Limited", status=UserStatus.ACTIVE.value, email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s10-s4-key-routes", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _now():
    return datetime.now(timezone.utc)


# ── AC-10-36: the two permission keys exist and reach an existing tenant ────


def test_pull_permission_keys_exist_and_do_not_collide_with_core(db):
    keys = {p.key for p in PermissionRepository(db).list_all()}
    assert "autocount.pull.read" in keys
    assert "autocount.pull.manage" in keys


def test_an_already_provisioned_tenants_admin_holds_both_keys_after_update(db):
    """AC-10-36's own grant-sweep test: `update_tenant` re-runs the tenant
    Admin grant so a tenant that installed the module BEFORE this slice
    still ends up with both new keys - never a permission with no path to
    an existing tenant (a standing hard-fail rule)."""
    from modules.autocount.bootstrap import update_tenant

    update_tenant(db, DEFAULT_TENANT_ID, from_version="0.10.0")
    db.commit()

    admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").one()
    admin_keys = {p.key for p in admin.permissions}
    assert "autocount.pull.read" in admin_keys
    assert "autocount.pull.manage" in admin_keys


# ── AC-10-37: list / issue routes, permission-gated, wire shape pinned ──────


def test_issue_key_route_returns_the_plaintext_once_never_persisted_looking(client, db):
    headers = _auth(client)
    response = client.post(
        "/autocount/pull/keys",
        json={"name": "SRT integration", "companyIds": ["co-1"]},
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["plaintext"].startswith("fxa_live_")
    assert body["key"]["name"] == "SRT integration"
    assert body["key"]["companyIds"] == ["co-1"]
    assert "plaintext" not in body["key"]
    assert body["key"]["revokedAt"] is None


def test_list_keys_route_returns_a_bare_array_never_the_plaintext(client, db):
    headers = _auth(client)
    client.post(
        "/autocount/pull/keys", json={"name": "k1", "companyIds": ["co-1"]}, headers=headers,
    )
    response = client.get("/autocount/pull/keys", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert "plaintext" not in body[0]
    assert "keyHash" not in body[0]


def test_key_routes_require_manage_not_merely_read(client, db):
    _limited_user(db, ["autocount.pull.read"], "readonly-pull@example.com")
    headers = _auth(client, "readonly-pull@example.com", "limited1234")

    assert client.get("/autocount/pull/keys", headers=headers).status_code == 403
    assert client.post(
        "/autocount/pull/keys", json={"name": "x", "companyIds": []}, headers=headers,
    ).status_code == 403


def test_key_routes_scoped_to_the_tenant(client, db):
    """AC-10-47: keys are never resolved unscoped - a second tenant's Admin
    never sees this tenant's keys."""
    _other_tenant(db)
    default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    role = Role(
        tenant_id=OTHER_TENANT, name="Admin", description="", is_system=True,
    )
    role.permissions = [
        p for p in PermissionRepository(db).list_all()
        if p.key in ("autocount.pull.read", "autocount.pull.manage")
    ]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=OTHER_TENANT, email="other-admin@example.com",
        password=hash_password("limited1234"), name="Other Admin",
        status=UserStatus.ACTIVE.value, email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()

    mine = _auth(client)
    client.post("/autocount/pull/keys", json={"name": "mine", "companyIds": ["co-1"]}, headers=mine)

    theirs = _auth(client, "other-admin@example.com", "limited1234")
    response = client.get("/autocount/pull/keys", headers=theirs)
    assert response.status_code == 200, response.text
    assert response.json() == []


# ── Revoke - direct route ────────────────────────────────────────────────────


def test_revoke_route_returns_the_updated_key_synchronously(client, db):
    headers = _auth(client)
    issued = client.post(
        "/autocount/pull/keys", json={"name": "k", "companyIds": ["co-1"]}, headers=headers,
    ).json()
    key_id = issued["key"]["id"]

    response = client.post(f"/autocount/pull/keys/{key_id}/revoke", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == key_id
    assert body["revokedAt"] is not None


def test_revoke_route_404s_for_another_tenants_key(client, db):
    _other_tenant(db)
    from modules.autocount.services.pull_key_service import PullKeyService

    theirs, _plaintext = PullKeyService(db).issue(
        OTHER_TENANT, name="theirs", company_ids=["co-x"],
    )

    headers = _auth(client)
    response = client.post(f"/autocount/pull/keys/{theirs.id}/revoke", headers=headers)
    assert response.status_code == 404, response.text


# ── Revoke - the CORE deferred-action grace window (plan §2.6) ──────────────


def _park_and_lapse(db, admin, entity_id) -> PendingAction:
    """The house pattern (`test_autocount_deferred_repush.py::_park_and_lapse`)."""
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=ACTION_KEY, entity_type=ENTITY_TYPE, entity_id=entity_id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()
    return svc.commit_one(row)


def _admin(db) -> User:
    return db.query(User).filter(User.email == "demo@example.com").first()


def test_revoke_action_is_registered_beside_repush():
    action_def = deferred_action_for(ACTION_KEY)
    assert action_def.entity_type == ENTITY_TYPE
    assert action_def.permission == "autocount.pull.manage"


def test_park_then_lapsed_commit_revokes_the_key(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    key, _plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="k", company_ids=["co-1"],
    )
    assert key.revoked_at is None  # control: unrevoked before the park/commit
    admin = _admin(db)

    result = _park_and_lapse(db, admin, key.id)
    assert result.status == "committed", result.error_text

    db.refresh(key)
    assert key.revoked_at is not None


def test_park_on_another_tenants_key_is_404(client, db):
    _other_tenant(db)
    from modules.autocount.services.pull_key_service import PullKeyService

    theirs, _plaintext = PullKeyService(db).issue(
        OTHER_TENANT, name="theirs", company_ids=["co-x"],
    )

    response = client.post(
        "/api/v1/pending-actions",
        headers=_auth(client),
        json={"actionKey": ACTION_KEY, "entityType": ENTITY_TYPE, "entityId": theirs.id},
    )
    assert response.status_code == 404, response.text


def test_park_by_a_read_only_user_is_403(client, db):
    from modules.autocount.services.pull_key_service import PullKeyService

    key, _plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="k", company_ids=["co-1"],
    )
    _limited_user(db, ["autocount.pull.read"], "readonly-revoke@example.com")

    response = client.post(
        "/api/v1/pending-actions",
        headers=_auth(client, "readonly-revoke@example.com", "limited1234"),
        json={"actionKey": ACTION_KEY, "entityType": ENTITY_TYPE, "entityId": key.id},
    )
    assert response.status_code == 403, response.text


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_key_routes_scoped_to_the_tenant dies if the list query is not
#   tenant-filtered - a second tenant would see the first tenant's key names.
# * test_revoke_route_404s_for_another_tenants_key and
#   test_park_on_another_tenants_key_is_404 die if either revoke path
#   resolves the key id with an unscoped lookup (AC-10-47).
# * test_park_then_lapsed_commit_revokes_the_key dies if the executor is
#   registered but wired to the wrong service method (e.g. a no-op stub) -
#   the control assertion (`revoked_at is None` beforehand) rules out a
#   fixture that was already revoked from a previous step.

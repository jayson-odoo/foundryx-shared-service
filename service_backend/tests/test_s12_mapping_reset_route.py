"""Sprint-5/12 S2 - RED before the coder: `POST .../mapping/reset-preset`.

Plan section 2.2 pins the exact route: `POST /autocount/companies/{company_id}
/entities/{entity_type}/mapping/reset-preset`, body `{dryRun: bool = True}`,
`require_permission("autocount.companies.manage")`, a uniform 404 for a
cross-tenant company id, and a 422 `{"detail": "No preset is registered for
this entity."}` for an entity with no registered preset.

AC-12-10 (permission + cross-tenant 404 + no-preset 422, "test all three"),
AC-12-31 (tenant scoping, folded into the cross-tenant case here per the
UAC's own note "covered inside AC-12-10 tests"), AC-12-30 (no new
permission) and AC-12-32 (no migration) as standing guards.

RED before the coder: the route does not exist at all yet, so every call
below 404s at the FastAPI ROUTING level (no matching path) - the "missing
feature" RED, not a fixture bug. Once the coder adds the route, the
permission test's `limited` call must read 403 (not 404) and the no-preset
call must read 422 (not 404) - the positive controls in each test exist so a
future regression (route silently removed again) cannot pass vacuously.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_SUPPLIER
from modules.autocount.models import AcCompany, AcEntityConfig, SOURCE_IMPL_AUTOCOUNT_HTTP

OTHER_TENANT = "tenant-other-s12-reset"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── shared helpers (house style, mirrors test_s10_s3_pull_operator_routes.py) ─


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _limited_user(db, keys: List[str], email: str) -> None:
    perms = PermissionRepository(db)
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in perms.list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password("limited1234"),
        name="Limited",
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa.func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s12-reset", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _connection(db, *, tenant_id: str = DEFAULT_TENANT_ID, name: str = "Mocha REST") -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=name,
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, tenant_id: str = DEFAULT_TENANT_ID, database_name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=tenant_id, connection_id=connection_id, database_name=database_name,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_config(db, company: AcCompany, connection_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> AcEntityConfig:
    """A product HTTP task with an empty mapping - `product` HAS a registered
    preset (`HTTP_PRESETS[ENTITY_PRODUCT]`), so this is the "happy path"
    entity for the permission/cross-tenant controls."""
    config = AcEntityConfig(
        tenant_id=tenant_id, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
        result_columns=None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _no_preset_config(db, company: AcCompany, connection_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> AcEntityConfig:
    """`supplier` is registered in neither `HTTP_PRESETS` nor
    `DOCUMENT_PRESETS` (sprint-5/12 baseline, `presets.py`) - the entity this
    plan's 422 branch exists for."""
    config = AcEntityConfig(
        tenant_id=tenant_id, company_id=company.id, entity_type=ENTITY_SUPPLIER,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        source_config={
            "connectionId": connection_id, "path": "/creditorbypage", "keyFields": ["AccNo"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
        result_columns=None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _reset_url(company_id: str, entity_type: str) -> str:
    return f"/autocount/companies/{company_id}/entities/{entity_type}/mapping/reset-preset"


# ── AC-12-10 (permission) ────────────────────────────────────────────────────


def test_ac_12_10_route_requires_companies_manage_permission(client, db):
    """A `companies.read`-only user must get 403 on BOTH `dryRun` values; a
    full-permission user (the positive control) must succeed - proving the
    403 is a real permission check, not the route being entirely absent."""
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-PERM")
    _product_config(db, company, conn.id)
    _limited_user(db, ["autocount.companies.read"], "s12-reset-reader@example.com")

    admin_headers = _auth(client)
    control = client.post(_reset_url(company.id, ENTITY_PRODUCT), json={"dryRun": True}, headers=admin_headers)
    assert control.status_code == 200, control.text

    limited_headers = _auth(client, "s12-reset-reader@example.com", "limited1234")
    for dry_run in (True, False):
        response = client.post(
            _reset_url(company.id, ENTITY_PRODUCT), json={"dryRun": dry_run}, headers=limited_headers
        )
        assert response.status_code == 403, (dry_run, response.text)


# ── AC-12-10 / AC-12-31 (cross-tenant, uniform 404) ─────────────────────────


def test_ac_12_10_31_cross_tenant_company_404s_both_dry_run_values(client, db):
    _other_tenant(db)
    their_conn = _connection(db, tenant_id=OTHER_TENANT, name="Their REST")
    their_company = _company(db, their_conn.id, tenant_id=OTHER_TENANT, database_name="THEIRS")
    _product_config(db, their_company, their_conn.id, tenant_id=OTHER_TENANT)

    # Positive control: the SAME entity type, on a company that DOES belong
    # to the authed tenant, succeeds - so the cross-tenant 404 is a genuine
    # tenant-scope guard, never the route resolving to a bare 404 vacuously.
    own_conn = _connection(db)
    own_company = _company(db, own_conn.id, database_name="OURS")
    _product_config(db, own_company, own_conn.id)

    headers = _auth(client)  # demo@example.com - DEFAULT_TENANT_ID
    control = client.post(_reset_url(own_company.id, ENTITY_PRODUCT), json={"dryRun": True}, headers=headers)
    assert control.status_code == 200, control.text

    for dry_run in (True, False):
        response = client.post(
            _reset_url(their_company.id, ENTITY_PRODUCT), json={"dryRun": dry_run}, headers=headers
        )
        assert response.status_code == 404, (dry_run, response.text)


# ── AC-12-10 (no preset registered -> 422 with the exact detail) ───────────


def test_ac_12_10_no_preset_registered_422s_with_exact_detail(client, db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-NOPRESET")
    _no_preset_config(db, company, conn.id)

    headers = _auth(client)
    for dry_run in (True, False):
        response = client.post(
            _reset_url(company.id, ENTITY_SUPPLIER), json={"dryRun": dry_run}, headers=headers
        )
        assert response.status_code == 422, (dry_run, response.text)
        assert response.json()["detail"] == "No preset is registered for this entity.", response.text


# ── AC-12-30 (no new permission) - standing guard, expected GREEN today ────


def test_ac_12_30_permissions_parity_no_new_key_added():
    """The route reuses `autocount.companies.manage`; the mapping view read
    stays on `autocount.companies.read` (plan D-nothing-new). Frozen against
    TODAY's key set (pre-S2) so a coder adding a new CSV row for this slice
    trips this test, not a silent grant-sweep gap."""
    csv_path = (
        Path(__file__).resolve().parents[1]
        / "modules" / "autocount" / "permissions" / "permissions.csv"
    )
    lines = [
        line for line in csv_path.read_text().splitlines()[1:] if line.strip()
    ]
    keys = set()
    for line in lines:
        resource, _label, action, *_rest = line.split(",")
        keys.add(f"{resource}.{action}")
    assert keys == {
        "autocount.companies.read",
        "autocount.companies.manage",
        "autocount.sync.read",
        "autocount.sync.run",
        "autocount.pull.read",
        "autocount.pull.manage",
    }, keys


# ── AC-12-32 (no migration) - standing guard, expected GREEN today ─────────


def test_ac_12_32_no_new_autocount_migration_added():
    """No schema change; `hasPreset` is derived at read time (plan 2.2). The
    highest revision on this branch's baseline is `0022_autocount_preview_
    job.py` - a reviewer/coder adding a migration for this slice trips this
    guard rather than the drift going unnoticed."""
    versions_dir = (
        Path(__file__).resolve().parents[1]
        / "modules" / "autocount" / "alembic" / "versions"
    )
    highest = 0
    for path in versions_dir.glob("*.py"):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    assert highest <= 22, (
        f"a new autocount migration (>0022) exists ({highest}) - AC-12-32 "
        "says this plan ships no schema change"
    )

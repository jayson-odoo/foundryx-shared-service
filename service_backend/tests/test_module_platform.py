"""Module platform v2 tests (sprint-3/10, F9) - validates AC-10-*.

topo order + cycle · version_satisfies · resolve_capability matrix (tenant-
active gated, exact-major) · duplicate boot error · active_modules filters a
catalog · soft-ref validate/resolve/orphan · requires guard + cascade · reverse-
dep guard on deactivate AND uninstall.
"""
import pytest

from app.module_platform import (
    CapabilityDef,
    DuplicateCapability,
    SoftRef,
    active_modules,
    check_dependents,
    check_requires,
    is_visible,
    register_capability,
    resolve_capability,
    resolve_install_order,
    resolve_soft_ref,
    validate_soft_ref,
)
from app.module_platform.dependencies import DependencyError, version_satisfies
from app.services.app_store_service import AppStoreService, DependentsActive, RequiresUnmet
from app.models.tenant import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def _admin(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── topo + version ──────────────────────────────────────────────────────────


def test_resolve_install_order_topological():
    manifests = [
        {"module_name": "a", "requires": [{"name": "b"}]},
        {"module_name": "b", "requires": [{"name": "c"}]},
        {"module_name": "c"},
    ]
    order = resolve_install_order(manifests)
    assert order.index("c") < order.index("b") < order.index("a")


def test_resolve_install_order_cycle_raises():
    manifests = [
        {"module_name": "a", "requires": [{"name": "b"}]},
        {"module_name": "b", "requires": [{"name": "a"}]},
    ]
    with pytest.raises(DependencyError):
        resolve_install_order(manifests)


def test_version_satisfies():
    assert version_satisfies("1.2.0", ">=1.0.0")
    assert not version_satisfies("0.9.0", ">=1.0.0")
    assert version_satisfies("1.0.0", None)
    assert not version_satisfies(None, ">=1.0.0")


# ── active_modules + is_visible ─────────────────────────────────────────────


def test_active_modules_includes_core_and_installed(session_factory):
    db = session_factory()
    active = active_modules(db, DEFAULT_TENANT_ID)
    assert "core" in active and "omnichannel" in active  # conftest installs omni
    assert is_visible("core", active) and is_visible("omnichannel", active)
    assert not is_visible("ghostmod", active)
    db.close()


# ── capability registry (D5) ────────────────────────────────────────────────


def test_resolve_capability_active_returns_handler(session_factory):
    db = session_factory()
    handler = resolve_capability(db, DEFAULT_TENANT_ID, "messaging.send", 1)
    assert handler is not None
    out = handler(db, DEFAULT_TENANT_ID, {"to": "+100", "body": "hi"})
    assert out["accepted"] is True and out["tenantId"] == DEFAULT_TENANT_ID
    db.close()


def test_resolve_capability_inactive_returns_none(client, session_factory):
    # Deactivate omnichannel for the default tenant → capability self-disables.
    h = _admin(client)
    client.post("/app-store/modules/omnichannel/deactivate", headers=h)
    db = session_factory()
    assert resolve_capability(db, DEFAULT_TENANT_ID, "messaging.send", 1) is None
    db.close()
    client.post("/app-store/modules/omnichannel/reactivate", headers=h)


def test_resolve_capability_absent_or_wrong_version(session_factory):
    db = session_factory()
    assert resolve_capability(db, DEFAULT_TENANT_ID, "messaging.send", 2) is None
    assert resolve_capability(db, DEFAULT_TENANT_ID, "nope.thing", 1) is None
    db.close()


def test_duplicate_capability_boot_error():
    with pytest.raises(DuplicateCapability):
        register_capability(
            CapabilityDef("messaging.send", 1, "another_module", lambda *a: None)
        )


# ── soft refs (D6) ──────────────────────────────────────────────────────────


def test_soft_ref_resolves_via_capability(session_factory):
    # Register a contact.resolve@1 provided by omnichannel (active for default).
    register_capability(
        CapabilityDef(
            "contact.resolve", 1, "omnichannel",
            lambda db, tid, payload: {"id": payload["id"], "name": "Resolved"},
        )
    )
    db = session_factory()
    ref = SoftRef(module="omnichannel", entity_type="contact", id="c1")
    resolved = resolve_soft_ref(db, DEFAULT_TENANT_ID, ref)
    assert resolved and resolved["name"] == "Resolved"
    assert validate_soft_ref(db, DEFAULT_TENANT_ID, ref) is True
    assert validate_soft_ref(db, DEFAULT_TENANT_ID, None) is True
    db.close()


def test_soft_ref_orphan_returns_none(client, session_factory):
    register_capability(
        CapabilityDef(
            "widget.resolve", 1, "omnichannel",
            lambda db, tid, payload: {"id": payload["id"]},
        )
    )
    h = _admin(client)
    client.post("/app-store/modules/omnichannel/deactivate", headers=h)
    db = session_factory()
    ref = SoftRef(module="omnichannel", entity_type="widget", id="w1")
    assert resolve_soft_ref(db, DEFAULT_TENANT_ID, ref) is None  # provider inactive
    assert validate_soft_ref(db, DEFAULT_TENANT_ID, ref) is False
    db.close()
    client.post("/app-store/modules/omnichannel/reactivate", headers=h)


# ── requires guard + reverse-dep guard (D4) ─────────────────────────────────


def test_check_requires_active_inactive_missing(client, session_factory):
    db = session_factory()
    svc = AppStoreService(db)
    # omnichannel is active → a manifest requiring it is satisfied.
    ok = check_requires(db, DEFAULT_TENANT_ID, {"module_name": "x", "requires": [{"name": "omnichannel"}]})
    assert ok["ok"] is True
    # a missing dep → not ok, listed under missing + cascade.
    miss = check_requires(db, DEFAULT_TENANT_ID, {"module_name": "x", "requires": [{"name": "ghostmod"}]})
    assert miss["ok"] is False and "ghostmod" in miss["cascade"]
    db.close()


def test_reverse_dep_guard_blocks_deactivate_and_uninstall(client, session_factory, monkeypatch):
    """A synthetic ACTIVE dependent requiring omnichannel blocks its removal."""
    # Inject a fake dependent manifest that requires omnichannel (check_dependents
    # imports discover_manifests from app.module_loader).
    fake = [
        {"module_name": "omnichannel"},
        {"module_name": "depmod", "requires": [{"name": "omnichannel"}]},
    ]
    monkeypatch.setattr("app.module_loader.discover_manifests", lambda *a, **k: fake)

    db = session_factory()
    # Force depmod into the active set by inserting a Module + TenantModule row.
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    m = Module(name="depmod", version="1.0.0", title="Dep", description="", is_listed=True)
    db.add(m)
    db.flush()
    db.add(TenantModule(tenant_id=DEFAULT_TENANT_ID, module_id=m.id, status=MODULE_STATUS_ACTIVE, installed_version="1.0.0"))
    db.commit()

    dependents = check_dependents(db, DEFAULT_TENANT_ID, "omnichannel")
    assert "depmod" in dependents

    svc = AppStoreService(db)
    with pytest.raises(DependentsActive):
        svc.deactivate(DEFAULT_TENANT_ID, "omnichannel")
    with pytest.raises(DependentsActive):
        svc.uninstall(DEFAULT_TENANT_ID, "omnichannel", "omnichannel")
    db.close()


def test_backfill_tenant_modules_runs_install_tenant_and_grants(client, session_factory):
    """B4 (plan-25 round-3 codex triage): a pre-App-Store tenant (module data
    exists, no `tenant_modules` row) must come out of `_backfill_tenant_modules`
    exactly as if it had gone through `AppStoreService.install` - the module's
    `install_tenant` seed hook ran (omnichannel: statuses + the workspace's
    lifecycle graph materialized) AND the module's permission keys were
    granted to the tenant's Admin role. Previously it was stamped ACTIVE at
    the current code version with NEITHER, and since installed_version was
    already current, no later `update_tenant` could ever repair it."""
    from app.models.module import Module, TenantModule
    from app.models.permission import Permission
    from app.models.role import Role, role_permissions
    from app.services.tenant_service import TenantService
    from app.module_loader import _backfill_tenant_modules
    from modules.omnichannel.models import Workspace

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Legacy Backfill Co", slug="legacy-backfill-co",
        admin_email="admin-legacybackfill@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    tenant_id = tenant.id

    # Simulate a pre-App-Store tenant: a Workspace row exists (the omnichannel
    # `tenant_has_data` detector) but NO `tenant_modules` row, and none of the
    # per-tenant seeding (`install_tenant`) has ever run.
    ws = Workspace(tenant_id=tenant_id, name="General", is_default=True, is_trashed=False)
    db.add(ws)
    db.commit()

    module = db.query(Module).filter(Module.name == "omnichannel").first()
    assert (
        db.query(TenantModule)
        .filter(TenantModule.tenant_id == tenant_id, TenantModule.module_id == module.id)
        .first()
        is None
    )

    _backfill_tenant_modules(db)
    db.commit()

    state = (
        db.query(TenantModule)
        .filter(TenantModule.tenant_id == tenant_id, TenantModule.module_id == module.id)
        .first()
    )
    assert state is not None and state.status == "ACTIVE"

    # install_tenant ran: the module's static status rows + the workspace's
    # lifecycle graph were materialized (not just the bare TenantModule row).
    from modules.omnichannel.models import Status as OmniStatus
    from modules.omnichannel.services import lifecycle_service

    assert (
        db.query(OmniStatus)
        .filter(OmniStatus.tenant_id == tenant_id, OmniStatus.scope == "WORKSPACE")
        .first()
        is not None
    )
    assert lifecycle_service.stages_for_workspace(db, tenant_id, ws.id) != []

    # The module's permission keys were granted to the tenant's Admin role.
    admin_role = (
        db.query(Role)
        .filter(Role.tenant_id == tenant_id, Role.name == "Admin")
        .first()
    )
    granted = {
        p.key
        for p in db.query(Permission)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .filter(role_permissions.c.role_id == admin_role.id)
        .all()
    }
    assert any(key.startswith("contacts.") for key in granted)
    db.close()


def test_backfill_tenant_modules_isolates_per_tenant_failure(client, session_factory, monkeypatch):
    """Pre-merge review follow-up (plan 25): one tenant's `install_tenant` hook
    raising must not corrupt the session for the rest of the backfill - it
    must roll back ONLY that tenant's `TenantModule` row + partial seed
    (`db.begin_nested()` SAVEPOINT), leaving the session usable so a later
    tenant in the same loop still installs cleanly and bootstrap completes."""
    from app.models.module import Module, TenantModule
    from app.services.tenant_service import TenantService
    from app.module_loader import _backfill_tenant_modules
    from modules.omnichannel.models import Workspace
    import modules.omnichannel.bootstrap as omni_bootstrap

    db = session_factory()
    tenant_a = TenantService(db).provision(
        name="Backfill Fail Co", slug="backfill-fail-co",
        admin_email="admin-backfillfail@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    tenant_b = TenantService(db).provision(
        name="Backfill Ok Co", slug="backfill-ok-co",
        admin_email="admin-backfillok@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

    # Both look like pre-App-Store tenants (a Workspace row, no tenant_modules row).
    db.add(Workspace(tenant_id=tenant_a_id, name="General", is_default=True, is_trashed=False))
    db.add(Workspace(tenant_id=tenant_b_id, name="General", is_default=True, is_trashed=False))
    db.commit()

    real_install_tenant = omni_bootstrap.install_tenant

    def _flaky_install_tenant(db_, tenant_id):
        if tenant_id == tenant_a_id:
            raise RuntimeError("boom - simulated install_tenant failure for tenant A")
        return real_install_tenant(db_, tenant_id)

    monkeypatch.setattr(omni_bootstrap, "install_tenant", _flaky_install_tenant)

    # Must not raise - the per-tenant failure is caught and isolated.
    _backfill_tenant_modules(db)
    db.commit()

    module = db.query(Module).filter(Module.name == "omnichannel").first()

    # Tenant A: no TenantModule row at all (fully rolled back).
    assert (
        db.query(TenantModule)
        .filter(TenantModule.tenant_id == tenant_a_id, TenantModule.module_id == module.id)
        .first()
        is None
    )

    # Tenant B: installed ACTIVE (bootstrap continued past A's failure).
    state_b = (
        db.query(TenantModule)
        .filter(TenantModule.tenant_id == tenant_b_id, TenantModule.module_id == module.id)
        .first()
    )
    assert state_b is not None and state_b.status == "ACTIVE"

    # The session itself stayed usable (no PendingRollbackError) - prove it
    # with an ordinary write on the same session.
    db.add(Workspace(tenant_id=tenant_b_id, name="Sanity Check", is_default=False, is_trashed=False))
    db.commit()
    db.close()


# ── terminology active-filter (D2) ──────────────────────────────────────────


def test_terminology_filters_inactive_module_terms(client, session_factory):
    from app.terminology.registry import TermDef, register_term

    register_term(TermDef("ghost_entity", "Ghost", "Ghosts", module="ghostmod"))
    register_term(TermDef("omni_thing", "Thing", "Things", module="omnichannel"))
    h = _admin(client)
    catalog = {i["key"]: i for i in client.get("/terminology/catalog", headers=h).json()}
    assert "omni_thing" in catalog  # omnichannel active
    assert "ghost_entity" not in catalog  # ghostmod not installed

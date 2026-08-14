"""Ideation module scaffold - Slice 1 (AC-A-01, AC-A-02, AC-A-45 partial).

Manifest discovery + fields, global install idempotency (module appears once in
the catalog), and permission-CSV sync. Mirrors the omnichannel scaffold contract.
"""
import pytest

from app.module_loader import discover_manifests

# The Phase-A ideation permission keys (PLAN §5 / AC-A-36). Keys are the flat
# `<resource>.<action>` form; the `ideation.` resource namespace keeps them
# globally unique alongside the core catalog's `products.*` keys.
IDEATION_PERMISSION_KEYS = {
    "ideation.products.manage",
    "ideation.ideas.view",
    "ideation.ideas.submit",
    "ideation.ideas.upvote",
    "ideation.triage.manage",
    "ideation.clusters.manage",
    "ideation.bindings.manage",
    "ideation.business_requirements.read",
    "ideation.business_requirements.manage",
    "ideation.business_requirements.promote",
}


def _ideation_manifest():
    for manifest in discover_manifests():
        if manifest["module_name"] == "ideation":
            return manifest
    return None


def test_manifest_discovered_and_fields():
    """AC-A-01: manifest is discovered with the module contract fields."""
    manifest = _ideation_manifest()
    assert manifest is not None, "ideation manifest not discovered"
    assert manifest["module_name"] == "ideation"
    assert manifest["schema"] == "app_ideation"
    assert manifest["alembic_version_table"] == "alembic_version_ideation"
    # `requires` uses the runtime object form the dependency resolver consumes
    # (``req["name"]``); the AC's ``["omnichannel"]`` is doc shorthand. The
    # module declares a hard dependency on omnichannel either way.
    require_names = {r["name"] for r in manifest["requires"]}
    assert require_names == {"omnichannel"}
    assert manifest["permissions_csv"] == "permissions/permissions.csv"


def test_manifest_declares_ideas_and_public_intake_routers():
    """AC-A-01 / AC-A-45 (partial): an `ideas` router and a public `intake` router."""
    manifest = _ideation_manifest()
    assert manifest is not None
    routers = {r["name"]: r for r in manifest.get("routers", [])}
    assert "ideas" in routers, "ideas router not declared"
    assert "intake" in routers, "intake router not declared"
    # The ideas (operator) router stays gated; intake is integration-key authed,
    # so it is a public router (no authenticated user to resolve a tenant from).
    assert not routers["ideas"].get("public"), "ideas router must stay gated"
    assert routers["intake"].get("public") is True, "intake router must be public"


def test_permission_csv_synced(ideation_session_factory):
    """AC-A-02: install syncs the ideation permission catalog rows."""
    from app.models.permission import Permission

    db = ideation_session_factory()
    try:
        keys = {
            p.key
            for p in db.query(Permission).filter(Permission.module == "ideation").all()
        }
        assert IDEATION_PERMISSION_KEYS <= keys, (
            f"missing keys: {IDEATION_PERMISSION_KEYS - keys}"
        )
    finally:
        db.close()


def test_install_idempotent_and_module_once(ideation_session_factory):
    """AC-A-02: a second global bootstrap is a no-op - module + perms not duplicated."""
    from app.models.module import Module
    from app.models.permission import Permission
    from app.module_loader import bootstrap_modules

    db = ideation_session_factory()
    try:
        engine = db.get_bind()
        # The fixture already bootstrapped + installed once; run it again.
        bootstrap_modules(engine=engine, db=db)

        modules = db.query(Module).filter(Module.name == "ideation").all()
        assert len(modules) == 1, "ideation must appear exactly once in the catalog"

        perms = db.query(Permission).filter(Permission.module == "ideation").all()
        keys = [p.key for p in perms]
        assert len(keys) == len(set(keys)), "duplicate permission rows after re-run"
        assert set(keys) == IDEATION_PERMISSION_KEYS
    finally:
        db.close()


def test_module_installed_active_for_default_tenant(ideation_session_factory):
    """AC-A-02/03 (partial): the module is installed ACTIVE for the default tenant."""
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
    from app.models.tenant import DEFAULT_TENANT_ID

    db = ideation_session_factory()
    try:
        module = db.query(Module).filter(Module.name == "ideation").one()
        state = (
            db.query(TenantModule)
            .filter(
                TenantModule.tenant_id == DEFAULT_TENANT_ID,
                TenantModule.module_id == module.id,
            )
            .one()
        )
        assert state.status == MODULE_STATUS_ACTIVE
    finally:
        db.close()

"""Meetings module scaffold - AC-S0-1, AC-S0-2, AC-S0-3.

Manifest discovery, the ten-table shape, the permission catalog + the Admin
grant that comes with a tenant install, the module gate, and the per-tenant
uninstall wipe.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.module_loader import discover_manifests
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

MEETINGS_PERMISSION_KEYS = {
    "meetings.view",
    "meetings.manage",
    "meetings.settings.manage",
}

# The ten tables from the program spine §3 - all of them land in migration 0001.
MEETINGS_TABLES = {
    "user_opt_ins",
    "calendar_events",
    "meetings",
    "meeting_participants",
    "transcripts",
    "transcript_segments",
    "minutes",
    "action_items",
    "shares",
    "tenant_settings",
}

OTHER_TENANT_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def meetings_client(meetings_session_factory):
    def override_get_db():
        db = meetings_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = meetings_session_factory
        yield c
    app.dependency_overrides.clear()


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _meetings_manifest():
    for manifest in discover_manifests():
        if manifest["module_name"] == "meetings":
            return manifest
    return None


def test_manifest_discovered_and_fields():
    """AC-S0-1: the manifest carries the module contract fields."""
    manifest = _meetings_manifest()
    assert manifest is not None, "meetings manifest not discovered"
    assert manifest["schema"] == "app_meetings"
    assert manifest["alembic_version_table"] == "alembic_version_meetings"
    assert manifest["permissions_csv"] == "permissions/permissions.csv"
    assert manifest["title"]
    assert manifest["icon"]
    routers = {r["name"] for r in manifest.get("routers", [])}
    assert {"optin", "events", "settings"} <= routers


def test_module_loaded_without_error():
    """A module that blows up at boot is skipped and behaves like inactive -
    which would make every other assertion here a false negative."""
    from app.module_loader import ERRORED_MODULES

    assert "meetings" not in ERRORED_MODULES, ERRORED_MODULES.get("meetings")


def test_ten_tables_in_the_module_schema():
    """AC-S0-1: the ten spine tables, all under ``app_meetings``."""
    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase

    names = {t.name for t in MeetingsBase.metadata.sorted_tables}
    assert names == MEETINGS_TABLES, names.symmetric_difference(MEETINGS_TABLES)
    for table in MeetingsBase.metadata.sorted_tables:
        assert table.schema == MEETINGS_SCHEMA, table.name


def test_permission_catalog_and_admin_grant(meetings_session_factory):
    """AC-S0-1: install syncs the three keys AND grants them to the tenant Admin."""
    from app.models.permission import Permission
    from app.models.role import Role

    db = meetings_session_factory()
    try:
        keys = {
            p.key for p in db.query(Permission).filter(Permission.module == "meetings").all()
        }
        assert keys == MEETINGS_PERMISSION_KEYS, keys.symmetric_difference(
            MEETINGS_PERMISSION_KEYS
        )

        admin = (
            db.query(Role)
            .filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin")
            .one()
        )
        granted = {p.key for p in admin.permissions}
        assert MEETINGS_PERMISSION_KEYS <= granted, MEETINGS_PERMISSION_KEYS - granted
    finally:
        db.close()


def test_install_seeds_the_tenant_settings_row(meetings_session_factory):
    """AC-S0-1: a tenant install leaves the module configured at defaults."""
    from modules.meetings.models import MeetingsTenantSettings

    db = meetings_session_factory()
    try:
        row = (
            db.query(MeetingsTenantSettings)
            .filter(MeetingsTenantSettings.tenant_id == DEFAULT_TENANT_ID)
            .one()
        )
        assert row.minutes_language == "en"
        assert row.audio_retention_days == 90
    finally:
        db.close()


def test_routes_403_without_the_module(client):
    """AC-S0-2: the default tenant of the CORE fixture has no meetings install."""
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    for path in ("/meetings/optin", "/meetings/events", "/meetings/settings"):
        got = client.get(path, headers=headers)
        assert got.status_code == 403, f"{path} -> {got.status_code} {got.text}"


def test_uninstall_wipes_only_this_tenants_rows(meetings_session_factory):
    """AC-S0-3: uninstall is per-tenant; the schema and other tenants survive."""
    from app.services.app_store_service import AppStoreService
    from modules.meetings.db import MeetingsBase
    from modules.meetings.models import CalendarEvent, MeetingsTenantSettings, UserOptIn
    from tests.meetings_helpers import make_tenant, utc

    db = meetings_session_factory()
    try:
        make_tenant(db, OTHER_TENANT_ID, "Other")
        AppStoreService(db).install(OTHER_TENANT_ID, "meetings")

        for tenant_id in (DEFAULT_TENANT_ID, OTHER_TENANT_ID):
            db.add(UserOptIn(tenant_id=tenant_id, user_id=f"u-{tenant_id}", enabled=True))
            db.add(
                CalendarEvent(
                    tenant_id=tenant_id,
                    external_id="ev-1",
                    calendar_user_id=f"u-{tenant_id}",
                    conference_url="https://meet.google.com/aaa-bbbb-ccc",
                    platform="meet",
                    starts_at=utc(2026, 9, 1, 2),
                )
            )
        db.commit()

        AppStoreService(db).uninstall(DEFAULT_TENANT_ID, "meetings", "meetings")
        db.commit()

        assert (
            db.query(CalendarEvent)
            .filter(CalendarEvent.tenant_id == DEFAULT_TENANT_ID)
            .count()
            == 0
        )
        assert (
            db.query(MeetingsTenantSettings)
            .filter(MeetingsTenantSettings.tenant_id == DEFAULT_TENANT_ID)
            .count()
            == 0
        )
        # The other tenant is untouched, and every table still exists.
        assert (
            db.query(CalendarEvent).filter(CalendarEvent.tenant_id == OTHER_TENANT_ID).count()
            == 1
        )
        assert (
            db.query(UserOptIn).filter(UserOptIn.tenant_id == OTHER_TENANT_ID).count() == 1
        )
        for table in MeetingsBase.metadata.sorted_tables:
            db.execute(table.select().limit(1))
    finally:
        db.close()

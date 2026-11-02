"""Plan 45 - job reads follow the type's read permission (AC-45-01..07).

Every registered job type names the permission that reads it; the Jobs list
and detail routes honour it per request, and a handler crash stores a fixed
sentence naming only the exception class.
"""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

from app.jobs.registry import (
    JobHandlerDef,
    _REGISTRY,
    list_job_handlers,
    register_job_handler,
)
from app.jobs.service import run_job
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from tests.connector_support import seed_user_with_perms

BACKEND = Path(__file__).resolve().parent.parent

READ_PERMISSIONS = {
    "storage_migration": "integrations.migrate_storage",
    "autocount_doc_feed_run": "autocount.sync.read",
    "autocount_sync": "autocount.sync.read",
    "autocount_doc_feed_backfill": "autocount.companies.read",
    "autocount_source_preview": "autocount.companies.read",
    "autocount_doc_lookup": "autocount.pull.read",
    "autocount_pull_snapshot": "autocount.pull.read",
    "meetings.calendar_sync": "meetings.settings.manage",
    "meetings.bot_run": "meetings.settings.manage",
    "meetings.transcribe": "meetings.settings.manage",
    "omnichannel.broadcast_send": "broadcasts.read",
    "omnichannel.contacts_export": "contacts.export",
    "omnichannel.respondio_migration": "omnichannel_migration.read",
    "omnichannel.report_export": "reports.export",
}
ALL_KEYS = sorted(set(READ_PERMISSIONS.values()))
NOT_FOUND = "Job not found."


def _login(client, email, password="Passw0rd!x", tenant_slug=None) -> dict:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _user(client, session_factory, perm_keys, tag):
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    seed_user_with_perms(session_factory, email, list(perm_keys))
    return _login(client, email)


def _seed_job(session_factory, job_type, tenant_id=DEFAULT_TENANT_ID, status="pending"):
    db = session_factory()
    try:
        job = BackgroundJob(tenant_id=tenant_id, type=job_type, status=status)
        db.add(job)
        db.commit()
        return job.id
    finally:
        db.close()


def _loaded_app_registry(client):
    from app.module_loader import boot_module_hooks

    boot_module_hooks()
    return list_job_handlers()


def _catalog_keys() -> set:
    keys = set()
    paths = [BACKEND / "app/permissions/permissions.csv"]
    paths += sorted(BACKEND.glob("modules/*/permissions/permissions.csv"))
    for path in paths:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                keys.add(f"{row['resource']}.{row['action']}")
    return keys


@pytest.fixture
def temp_handlers():
    added = []

    def _add(def_: JobHandlerDef):
        register_job_handler(def_)
        added.append(def_.type)

    yield _add
    for t in added:
        _REGISTRY.pop(t, None)


# ── AC-45-01 / AC-45-06: the registry names a read key per type ──────────────
def test_ac_45_01_every_registered_type_names_a_catalog_read_permission(client):
    defs = _loaded_app_registry(client)
    types = {d.type for d in defs}
    assert set(READ_PERMISSIONS) <= types, sorted(set(READ_PERMISSIONS) - types)
    catalog = _catalog_keys()
    for d in defs:
        key = getattr(d, "read_permission", None)
        assert key, f"{d.type} names no read permission"
        assert key in catalog, f"{d.type}: {key} is in no permissions.csv"


def test_ac_45_06_read_permission_per_type(client):
    defs = {d.type: d for d in _loaded_app_registry(client)}
    got = {t: getattr(defs[t], "read_permission", None) for t in READ_PERMISSIONS if t in defs}
    assert got == READ_PERMISSIONS


# ── AC-45-02: the list holds only readable types ─────────────────────────────
def test_ac_45_02_list_holds_only_types_the_caller_may_read(client, session_factory):
    _loaded_app_registry(client)
    ids = {
        t: _seed_job(session_factory, t)
        for t in ("autocount_sync", "omnichannel.respondio_migration", "storage_migration")
    }
    a = _user(client, session_factory, ["autocount.sync.read"], "reader")
    body = client.get("/jobs", headers=a).json()
    assert [i["id"] for i in body["items"]] == [ids["autocount_sync"]]
    assert body["total"] == 1


def test_ac_45_02_type_filter_for_an_unreadable_type_is_an_empty_page(client, session_factory):
    _loaded_app_registry(client)
    _seed_job(session_factory, "omnichannel.respondio_migration")
    a = _user(client, session_factory, ["autocount.sync.read"], "reader")
    body = client.get("/jobs", params={"type": "omnichannel.respondio_migration"}, headers=a).json()
    assert body == {"items": [], "total": 0}


def test_ac_45_02_caller_with_no_job_keys_gets_an_empty_page(client, session_factory):
    _loaded_app_registry(client)
    for t in ("autocount_sync", "storage_migration"):
        _seed_job(session_factory, t)
    nobody = _user(client, session_factory, [], "nokeys")
    body = client.get("/jobs", headers=nobody).json()
    assert body == {"items": [], "total": 0}


def test_ac_45_02_holder_of_every_job_key_sees_all(client, session_factory):
    _loaded_app_registry(client)
    ids = {
        _seed_job(session_factory, t)
        for t in ("autocount_sync", "omnichannel.respondio_migration", "storage_migration")
    }
    admin = _user(client, session_factory, ALL_KEYS, "allkeys")
    body = client.get("/jobs", headers=admin).json()
    assert {i["id"] for i in body["items"]} == ids
    assert body["total"] == 3


# ── AC-45-03: detail for an unreadable type is a plain 404 ───────────────────
def test_ac_45_03_detail_of_an_unreadable_type_answers_not_found(client, session_factory):
    _loaded_app_registry(client)
    job_id = _seed_job(session_factory, "omnichannel.respondio_migration")
    a = _user(client, session_factory, ["autocount.sync.read"], "reader")
    res = client.get(f"/jobs/{job_id}", headers=a)
    missing = client.get(f"/jobs/{uuid.uuid4()}", headers=a)
    assert res.status_code == 404
    assert res.json() == missing.json() == {"detail": NOT_FOUND}


# ── AC-45-04: a type with no handler is listed to nobody ─────────────────────
def test_ac_45_04_unregistered_type_is_not_listed_and_answers_not_found(client, session_factory):
    _loaded_app_registry(client)
    job_id = _seed_job(session_factory, "t45.no_such_type")
    admin = _user(client, session_factory, ALL_KEYS, "allkeys")
    body = client.get("/jobs", headers=admin).json()
    assert job_id not in {i["id"] for i in body["items"]}
    assert client.get(f"/jobs/{job_id}", headers=admin).status_code == 404


# ── AC-45-05: a crash stores the class name only ─────────────────────────────
def _run_crashing(session_factory, temp_handlers, exc):
    def _boom(db, job):
        raise exc

    job_type = f"t45.crash_{uuid.uuid4().hex[:6]}"
    temp_handlers(JobHandlerDef(job_type, _boom, "Crash probe"))
    job_id = _seed_job(session_factory, job_type)
    db = session_factory()
    try:
        run_job(db, job_id)
    finally:
        db.close()
    db = session_factory()
    try:
        return db.get(BackgroundJob, job_id)
    finally:
        db.close()


def test_ac_45_05_handler_crash_stores_the_class_name_only(session_factory, temp_handlers):
    job = _run_crashing(session_factory, temp_handlers, RuntimeError("MARKER-CRASH text"))
    assert job.status == "failed"
    assert job.error == "Job crashed (RuntimeError)."
    row = json.dumps(
        [job.error, job.result_json, job.logs_json, job.payload_json, job.cursor_json],
        default=str,
    )
    assert "MARKER" not in row


def test_ac_45_05_storage_connection_sentence_is_unchanged(session_factory, temp_handlers):
    from app.services.storage import UnresolvableKey

    job = _run_crashing(session_factory, temp_handlers, UnresolvableKey("conn:MARKER-ID:x"))
    assert job.status == "failed"
    assert job.error == "Job stopped: a storage connection is not usable."


# ── AC-45-07: a holder of the type's key reads as before ─────────────────────
def test_ac_45_07_export_poller_reads_its_job_by_the_exports_key(client, session_factory):
    _loaded_app_registry(client)
    job_id = _seed_job(session_factory, "omnichannel.contacts_export", status="done")
    u = _user(client, session_factory, ["contacts.export"], "exporter")
    res = client.get(f"/jobs/{job_id}", headers=u)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == job_id and body["type"] == "omnichannel.contacts_export"
    assert set(body) == {
        "id", "tenantId", "type", "status", "actorUserId", "payload", "result", "logs",
        "progressTotal", "progressDone", "progressFailed", "error",
        "createdAt", "startedAt", "finishedAt",
    }
    listed = client.get("/jobs", headers=u).json()
    assert [i["id"] for i in listed["items"]] == [job_id]


# ── tenant scope stays beside the type filter ────────────────────────────────
def test_ac_45_02_other_tenant_job_of_a_readable_type_is_not_listed(client, session_factory):
    from app.services.tenant_service import TenantService

    _loaded_app_registry(client)
    db = session_factory()
    try:
        other = TenantService(db).provision(
            name="Other Jobs", slug="other-jobs", admin_email="admin-other-jobs@example.com",
            admin_password="Password123!", admin_name="Admin",
        )
        db.commit()
        other_id = other.id
    finally:
        db.close()
    foreign = _seed_job(session_factory, "autocount_sync", tenant_id=other_id)
    own = _seed_job(session_factory, "autocount_sync")
    a = _user(client, session_factory, ["autocount.sync.read"], "reader")
    body = client.get("/jobs", headers=a).json()
    assert [i["id"] for i in body["items"]] == [own]
    assert body["total"] == 1
    assert client.get(f"/jobs/{foreign}", headers=a).status_code == 404

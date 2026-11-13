"""Shared fixtures for lane SS-MIGRATION-SYNC (plan sprint-5/52) red tests.

No tests live here. The sync tests import:
  * `FakeRespondIo` - a respond.io whose contacts / channels / messages can be
    mutated BETWEEN ticks (a new message "arriving"), that logs every request
    and can answer 401 / 429 / per-path errors. It is installed through the
    same `RespondIoClient.from_connection` monkeypatch the migration suites use
    (an `httpx.MockTransport`), so nothing here ever reaches a real host.
  * `World` / `new_world` - tenant data chain (workspace, respondio connection,
    WhatsApp channel, fake) built per test, plus `run_migration` which runs a
    real one-off migration so the sync starts from a genuine DONE run job.
  * small row helpers (`set_sync`, `make_due`, `sync_jobs`, ...).

Models / services of the feature under test are imported LAZILY inside the
helpers so a missing module fails each test individually (ImportError) rather
than erroring the whole file at collection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import json
import httpx

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob

from modules.omnichannel.models import (
    Contact,
    ConversationMessage,
    MigrationRef,
)
from modules.omnichannel.services.migration_service import (
    MIGRATION_JOB_TYPE,
    register_migration_job_handler,
    run_migration_job,
)

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _default_workspace,
    _make_connection,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import _make_channel, _make_full_job

SOURCE_CHANNEL = 1001
SYNC_JOB_TYPE_LITERAL = "omnichannel.respondio_sync"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ── lazy access to the feature under test ───────────────────────────────────


def sync_models():
    from modules.omnichannel.models import MigrationSync, MigrationSyncHint

    return MigrationSync, MigrationSyncHint


def sync_service_module():
    from modules.omnichannel.services import migration_sync_service

    return migration_sync_service


def run_due_syncs(db):
    return sync_service_module().run_due_syncs(db)


# ── fake respond.io ─────────────────────────────────────────────────────────


class FakeRespondIo:
    """Mutable in-memory respond.io. `calls` = [(method, path)] in order."""

    def __init__(self) -> None:
        self.contacts: Dict[int, Dict[str, Any]] = {}
        self.messages: Dict[int, List[Dict[str, Any]]] = {}
        self.channels: Dict[int, List[Dict[str, Any]]] = {}
        self.custom_fields: List[Dict[str, Any]] = []
        self.calls: List[tuple] = []
        # JSON bodies of POST /contact/list, in order (respond.io's required
        # `search` + `filter` keys, #182/#184).
        self.contact_list_bodies: List[Any] = []
        self.fail_all: Optional[int] = None
        self.fail_paths: Dict[str, int] = {}
        self.rate_limited = False
        self.hooks: List[Any] = []
        self.last_message_list_at: Optional[datetime] = None
        self._base_ts = int((utcnow() - timedelta(days=5)).timestamp())

    # -- seeding / mutation --------------------------------------------------

    def add_contact(
        self, cid: int, *, first: str = "Zed", last: Optional[str] = None, phone: Optional[str] = None,
        email: Optional[str] = None, language: Optional[str] = None, country: Optional[str] = None,
        tags: Optional[List[str]] = None, lifecycle: Optional[str] = None, status: str = "open",
        assignee: Optional[Dict[str, Any]] = None, custom_fields: Optional[List[Dict[str, Any]]] = None,
        source_channel: int = SOURCE_CHANNEL,
    ) -> Dict[str, Any]:
        phone = phone or f"+601000{cid}"
        row: Dict[str, Any] = {
            "id": cid, "firstName": first, "lastName": last, "phone": phone, "email": email,
            "language": language, "countryCode": country, "tags": tags or [], "lifecycle": lifecycle,
            "status": status, "assignee": assignee, "custom_fields": custom_fields or [],
            "created_at": self._base_ts - 86400,
        }
        self.contacts[cid] = row
        self.messages.setdefault(cid, [])
        self.channels[cid] = [
            {"id": source_channel, "name": "WA", "source": "whatsapp", "meta": {"phone": phone}}
        ]
        return row

    def set_contact(self, cid: int, **fields: Any) -> None:
        self.contacts[cid].update(fields)

    def add_message(
        self, cid: int, mid: int, *, traffic: str = "incoming", text: str = "hello",
        ts: Optional[int] = None, channel_message_id: Optional[str] = None,
        channel_id: Optional[int] = SOURCE_CHANNEL,
    ) -> Dict[str, Any]:
        # `mid` is the per-contact sequence number; the respond.io messageId is
        # global (refs are keyed on it per workspace), so it is derived from cid.
        ts = ts if ts is not None else self._base_ts + mid * 60
        item = {
            "messageId": cid * 100 + mid, "traffic": traffic, "channelId": channel_id,
            "channelMessageId": channel_message_id,
            "message": {"type": "text", "text": text},
            "status": [{"value": "sent" if traffic == "outgoing" else "read", "timestamp": ts}],
        }
        self.messages.setdefault(cid, []).append(item)
        return item

    # -- introspection -------------------------------------------------------

    def count(self, method: str, fragment: str) -> int:
        return sum(1 for m, p in self.calls if m == method and fragment in p)

    @property
    def contact_list_calls(self) -> int:
        return self.count("POST", "/contact/list")

    def message_list_calls(self, cid: int) -> int:
        return self.count("GET", f"/contact/id:{cid}/message/list")

    def contact_get_calls(self, cid: int) -> int:
        return sum(1 for m, p in self.calls if m == "GET" and p.endswith(f"/contact/id:{cid}"))

    def clear_calls(self) -> None:
        self.calls.clear()

    # -- transport -----------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.calls.append((method, path))
        if method == "POST" and path.endswith("/contact/list"):
            try:
                self.contact_list_bodies.append(json.loads(request.content or b"null"))
            except ValueError:
                self.contact_list_bodies.append(None)
        for hook in list(self.hooks):
            hook(method, path)
        if path.endswith("/message/list"):
            self.last_message_list_at = utcnow()
        if self.rate_limited:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"code": 429, "message": "Too many requests"})
        if self.fail_all:
            return httpx.Response(self.fail_all, json={"code": self.fail_all, "message": "rejected"})
        for fragment, code in self.fail_paths.items():
            if fragment in path:
                return httpx.Response(code, json={"code": code, "message": "vendor error"})

        def page(items: list) -> httpx.Response:
            return httpx.Response(200, json={"items": items, "pagination": {"next": None}})

        if path.endswith("/space/custom_field"):
            return page(self.custom_fields)
        if path.endswith("/space/user"):
            return page([])
        if path.endswith("/space/channel"):
            return page([{"id": SOURCE_CHANNEL, "name": "WA Main", "source": "whatsapp"}])
        if path.endswith("/contact/list"):
            return page(list(self.contacts.values()))
        if path.endswith("/channels"):
            cid = int(path.split("/contact/id:")[1].split("/")[0])
            return page(self.channels.get(cid, []))
        if path.endswith("/message/list"):
            cid = int(path.split("/contact/id:")[1].split("/")[0])
            return page(list(self.messages.get(cid, [])))
        if "/contact/id:" in path:
            cid = int(path.split("/contact/id:")[1])
            if cid in self.contacts:
                return httpx.Response(200, json=self.contacts[cid])
            return httpx.Response(404, json={"code": 404, "message": "Contact not found"})
        return httpx.Response(404, json={"code": 404, "message": "unknown route"})


# ── world: the tenant data chain, built per test ────────────────────────────


_OPEN_WORLDS: List["World"] = []


def close_all_worlds() -> None:
    """Autouse-fixture teardown (see the two test files): a session left open
    would be committed by `app.database.release_read_transactions` against a
    disposed engine in a later test and log a spurious warning."""
    while _OPEN_WORLDS:
        _OPEN_WORLDS.pop().db.close()


class World:
    def __init__(self, db, ws, conn, channel, fake):
        _OPEN_WORLDS.append(self)
        self.db = db
        self.ws = ws
        self.conn = conn
        self.channel = channel
        self.fake = fake
        self.tenant_id = DEFAULT_TENANT_ID
        self.job: Optional[BackgroundJob] = None

    def run_migration(self, *, channel_target: Optional[str] = "mapped", lifecycle_map=None) -> BackgroundJob:
        """A REAL one-off migration (run mode, API source, all phases) over the
        fake as it stands now. `channel_target="mapped"` maps the source
        channel to the world's WhatsApp channel; None skips it."""
        target = self.channel.id if channel_target == "mapped" else channel_target
        job = _make_full_job(
            self.db, self.tenant_id, connection_id=self.conn.id, workspace_id=self.ws.id, mode="run",
            channel_map=[{"sourceChannelId": str(SOURCE_CHANNEL), "targetChannelId": target}],
        )
        if lifecycle_map:
            job.payload_json = {**job.payload_json, "lifecycleMap": lifecycle_map}
            self.db.commit()
        run_migration_job(self.db, job)
        self.db.refresh(job)
        assert job.status == JOB_DONE, job.error
        if job.finished_at is None:  # pragma: no cover - finish() sets it
            job.finished_at = utcnow()
            self.db.commit()
        self.job = job
        return job

    def contact_by_cid(self, cid: int) -> Optional[Contact]:
        self.db.expire_all()
        ref = (
            self.db.query(MigrationRef)
            .filter(
                MigrationRef.tenant_id == self.tenant_id, MigrationRef.workspace_id == self.ws.id,
                MigrationRef.entity_type == "contact", MigrationRef.external_id == str(cid),
            )
            .first()
        )
        if ref is None:
            return None
        return self.db.query(Contact).filter(
            Contact.id == ref.local_id, Contact.tenant_id == self.tenant_id
        ).first()

    def contact_by_phone(self, phone: str) -> Optional[Contact]:
        self.db.expire_all()
        return self.db.query(Contact).filter(
            Contact.tenant_id == self.tenant_id, Contact.workspace_id == self.ws.id, Contact.phone == phone
        ).first()

    def messages_of(self, contact: Contact) -> List[ConversationMessage]:
        self.db.expire_all()
        return (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.tenant_id == self.tenant_id, ConversationMessage.contact_id == contact.id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )


def new_world(session_factory, monkeypatch, *, rps: str = "1000") -> World:
    """Workspace + respondio connection + WhatsApp channel + installed fake.
    Also registers the job handlers (registration normally happens at app
    boot; direct-DB tests never boot it)."""
    register_migration_job_handler()
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    conn.config_json = {**conn.config_json, "requestsPerSecond": rps}
    channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()
    fake = FakeRespondIo()
    _stub_client(monkeypatch, fake.handler)
    return World(db, ws, conn, channel, fake)


def add_done_job(
    db, ws, conn, *, mode: str = "run", source: str = "api", status: str = JOB_DONE,
    channel_target: Optional[str] = None, finished_at: Optional[datetime] = None,
    result: Optional[dict] = None,
) -> BackgroundJob:
    """A hand-built finished migration job row (for the 'which run counts'
    ACs and for later 'newer run' mappings)."""
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=status,
        payload_json={
            "mode": mode, "source": source, "connectionId": conn.id if conn is not None else None,
            "workspaceId": ws.id,
            "channelMap": [{"sourceChannelId": str(SOURCE_CHANNEL), "targetChannelId": channel_target}],
            "userMap": [], "teamMap": [], "lifecycleMap": [], "contactsOnly": False, "mappingHash": "h",
        },
        result_json=result,
        finished_at=finished_at or utcnow(),
    )
    db.add(job)
    db.commit()
    return job


# ── HTTP helpers ────────────────────────────────────────────────────────────

SYNCS = "/omnichannel/migration/syncs"


def create_sync(client, headers, workspace_id):
    return client.post(SYNCS, headers=headers, json={"workspaceId": workspace_id})


def start_sync(client, workspace_id, headers=None) -> dict:
    headers = headers or _auth(client)
    res = create_sync(client, headers, workspace_id)
    assert res.status_code == 201, res.text
    return res.json()


def get_sync(client, headers, sync_id) -> dict:
    res = client.get(f"{SYNCS}/{sync_id}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def webhook_path(client, headers, sync_id) -> str:
    """`/omnichannel/migration-hooks/{id}/{secret}` parsed out of GET /webhook."""
    res = client.get(f"{SYNCS}/{sync_id}/webhook", headers=headers)
    assert res.status_code == 200, res.text
    url = res.json()["url"]
    return urlparse(url).path


def post_hint(client, path: str, body: Any = None, **kw):
    if body is None:
        body = {"contact": {"id": 1}}
    return client.post(path, json=body, **kw)


# ── sync-row helpers (direct DB) ────────────────────────────────────────────


def sync_row(db, sync_id):
    MigrationSync, _ = sync_models()
    db.expire_all()
    return db.query(MigrationSync).filter(
        MigrationSync.id == sync_id, MigrationSync.tenant_id == DEFAULT_TENANT_ID
    ).first()


def set_sync(db, sync_id, **cols) -> None:
    MigrationSync, _ = sync_models()
    db.query(MigrationSync).filter(
        MigrationSync.id == sync_id, MigrationSync.tenant_id == DEFAULT_TENANT_ID
    ).update(cols, synchronize_session=False)
    db.commit()
    db.expire_all()


def make_due(db, sync_id, *, full_sweep: Optional[str] = "not_due") -> None:
    """`full_sweep`: 'not_due' (swept a minute ago), 'due' (swept 7 h ago),
    'never' (NULL), or None to leave the column alone."""
    cols: Dict[str, Any] = {"next_sync_at": utcnow() - timedelta(minutes=1)}
    if full_sweep == "not_due":
        cols["last_full_sweep_at"] = utcnow() - timedelta(minutes=1)
    elif full_sweep == "due":
        cols["last_full_sweep_at"] = utcnow() - timedelta(hours=7)
    elif full_sweep == "never":
        cols["last_full_sweep_at"] = None
    set_sync(db, sync_id, **cols)


def not_due(db, sync_id) -> None:
    set_sync(db, sync_id, next_sync_at=utcnow() + timedelta(minutes=10))


def sync_jobs(db) -> List[BackgroundJob]:
    db.expire_all()
    return (
        db.query(BackgroundJob)
        .filter(BackgroundJob.tenant_id == DEFAULT_TENANT_ID, BackgroundJob.type == SYNC_JOB_TYPE_LITERAL)
        .order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
        .all()
    )


def hint_ids(db, sync_id) -> List[str]:
    _, MigrationSyncHint = sync_models()
    db.expire_all()
    rows = db.query(MigrationSyncHint).filter(
        MigrationSyncHint.tenant_id == DEFAULT_TENANT_ID, MigrationSyncHint.sync_id == sync_id
    ).all()
    return sorted(r.external_contact_id for r in rows)


def stub_enqueue(monkeypatch) -> List[str]:
    """Replace `JobService.enqueue` with a recorder so enqueued jobs stay
    PENDING (the sweep tests need a job that is 'pending/running')."""
    from app.jobs.service import JobService

    enqueued: List[str] = []
    monkeypatch.setattr(JobService, "enqueue", lambda self, job_id: enqueued.append(job_id))
    return enqueued


def seam_counters(monkeypatch) -> Dict[str, int]:
    """Patch every live seam plan 33 D-A6-8 forbids; returns the call counter."""
    calls = {"publish": 0, "emit": 0, "notify": 0, "fan_out": 0, "enqueue_event": 0, "workspace_event": 0}

    import app.workflow_engine.entity_events as entity_events_module
    import modules.omnichannel.services.realtime as realtime_module
    import modules.omnichannel.services.webhook_delivery as webhook_delivery_module

    def bump(key):
        def _f(*a, **k):
            calls[key] += 1
        return _f

    monkeypatch.setattr(realtime_module, "publish", bump("publish"))
    monkeypatch.setattr(entity_events_module, "emit_entity_event", bump("emit"))
    monkeypatch.setattr(entity_events_module, "notify_entity_event", bump("notify"))
    monkeypatch.setattr(webhook_delivery_module, "_fan_out", bump("fan_out"))
    monkeypatch.setattr(webhook_delivery_module, "enqueue_event", bump("enqueue_event"))
    monkeypatch.setattr(webhook_delivery_module, "enqueue_workspace_event", bump("workspace_event"))
    return calls

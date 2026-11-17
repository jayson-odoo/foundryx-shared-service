"""Payload version 1 is frozen: byte snapshots of every existing consumer payload.

Every outbound webhook body of each event type in ``EVENT_TYPES`` and the main
API-key responses (contacts, messages, channels, templates, webhook endpoints,
send) are compared BYTE FOR BYTE with fixtures captured from the code before
payload versioning existed (``tests/fixtures/omnichannel_payload_snapshots``).
A consumer that never opts in to a higher version must keep getting exactly
these bytes, so a failure here means an existing consumer would see a change.

Volatile values (generated ids, clock times, signing secrets) are replaced by
placeholders before the compare; key order, spacing and every other byte are
compared as they went over the wire. Webhook bodies are the exact bytes that
were signed and POSTed.

Regenerate (only for a deliberate, reviewed change to version 1, which should
never happen): ``UPDATE_PAYLOAD_SNAPSHOTS=1 python -m pytest -q
tests/test_omnichannel_payload_snapshots.py`` and review the fixture diff.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import ConversationMessage, WhatsappTemplate
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.webhook_service import EVENT_TYPES
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)
from tests.test_omnichannel_consumer_webhooks import _reaction_payload
from tests.test_omnichannel_webhooks import _process, _wa_payload

BASE = "/api/v1/omnichannel"
HOOK = "https://hooks.example.com/snapshot"
PHONE = "+60123450001"
WA_FROM = "60123450001"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "fixtures" / "omnichannel_payload_snapshots"
UPDATE = os.environ.get("UPDATE_PAYLOAD_SNAPSHOTS") == "1"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_SECRET = re.compile(r"whsec_[A-Za-z0-9_-]+")
_EVENT_SUFFIX = re.compile(r'(<id\d+>):\d+:[0-9a-f]{8}"')
_EPOCH = re.compile(r'"(timestamp|created_at)":\d{10}\b')
_DEV_WAMID = re.compile(r"wamid\.dev[A-Za-z0-9._-]*")


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture(autouse=True)
def _tmp_media(tmp_path):
    from app.config import settings
    from app.services.storage import set_storage

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    yield
    settings.media_root = prev
    set_storage(None)


class _Resp:
    status_code = 200


@pytest.fixture
def posted(monkeypatch):
    """Every webhook POST (url, exact body bytes, headers); none reach the network.
    Queued deliveries are recorded and run by ``drain`` on the test database."""
    from modules.omnichannel import worker

    calls = []
    queued = []

    def _fake_post(url, *, content, headers, timeout):
        calls.append({"url": url, "content": content, "headers": dict(headers)})
        return _Resp()

    monkeypatch.setattr(wd, "_post", _fake_post)
    monkeypatch.setattr(worker.deliver_webhook, "delay", queued.append)
    return _Posted(calls, queued)


class _Posted(list):
    def __init__(self, calls, queued):
        super().__init__()
        self.calls, self.queued = calls, queued

    def drain(self, session_factory):
        """Run every queued delivery once, in queue order; returns the POSTs."""
        while self.queued:
            db = session_factory()
            try:
                wd.dispatch(db, self.queued.pop(0))
            finally:
                db.close()
        return self.calls


# ── helpers ──────────────────────────────────────────────────────────────────
def normalize(raw: bytes) -> str:
    """Replace volatile values with placeholders; every other byte is kept.
    Ids are numbered by first appearance within one payload."""
    text = raw.decode("utf-8")
    ids: Dict[str, str] = {}

    def _id(match):
        return ids.setdefault(match.group(0), f"<id{len(ids) + 1}>")

    text = _UUID.sub(_id, text)
    text = _TS.sub("<ts>", text)
    text = _SECRET.sub("<secret>", text)
    text = _EVENT_SUFFIX.sub(r'\1:<epoch>:<hex>"', text)
    text = _EPOCH.sub(r'"\1":<epoch>', text)
    text = _DEV_WAMID.sub("<wamid>", text)
    return text


def run_scenario(client, session_factory, posted, extra_headers: Optional[dict] = None) -> Dict[str, str]:
    """Drive every existing payload once and return ``name -> normalized bytes``.
    ``extra_headers`` ride every API-key request (used to prove that
    ``X-Fx-Api-Version: 1`` changes nothing)."""
    out: Dict[str, str] = {}
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone=PHONE, open_window=True)
    db = session_factory()
    db.add(
        WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID,
            channel_id=channel_id,
            name="welcome",
            language="en",
            status="APPROVED",
            category="UTILITY",
            components_json=[{"type": "BODY", "text": "Hello {{1}}"}],
        )
    )
    db.commit()
    db.close()
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}", **(extra_headers or {})}

    def api(name, method, path, expect, **kw):
        res = client.request(method, f"{BASE}{path}", headers=hdr, **kw)
        assert res.status_code == expect, (name, res.status_code, res.text)
        out[f"api.{name}"] = normalize(res.content)
        return res

    # Webhook endpoint routes (create answers the item inside the mint response).
    created = api(
        "webhooks.create", "POST", "/webhooks", 201,
        json={"name": "Snapshot", "url": HOOK, "events": list(EVENT_TYPES)},
    )
    eid = created.json()["endpoint"]["id"]
    api("webhooks.list", "GET", "/webhooks", 200)
    api("webhooks.update", "PATCH", f"/webhooks/{eid}", 200, json={"name": "Snapshot 2"})
    api("webhooks.disable", "POST", f"/webhooks/{eid}/disable", 200)
    api("webhooks.enable", "POST", f"/webhooks/{eid}/enable", 200)

    # Send: answers 202 and fires message.outbound + message.status SENT.
    api("messages.send", "POST", "/messages", 202,
        json={"to": PHONE, "type": "text", "text": {"body": "Hello from snapshot"}})
    db = session_factory()
    sent_ext = (
        db.query(ConversationMessage.external_message_id)
        .filter(ConversationMessage.body == "Hello from snapshot")
        .scalar()
    )
    db.close()

    # Inbound text, a delivery receipt for the send, and a reaction.
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.snap-in-1", from_=WA_FROM, text="Hi!"))
    if sent_ext:
        _process(
            session_factory,
            channel_id,
            _wa_payload(statuses=[{
                "id": sent_ext, "status": "delivered", "timestamp": "1717550100",
                "recipient_id": WA_FROM,
            }]),
        )
    _process(
        session_factory, channel_id,
        _reaction_payload(target_wamid="wamid.snap-in-1", emoji="\U0001f44d", from_=WA_FROM, wamid="wamid.snap-rx"),
    )

    # Contact writes and reads (contact.updated fires on the PATCH).
    cid = client.get(f"{BASE}/contacts/phone:{PHONE}", headers=hdr).json()["id"]
    api("contacts.update", "PATCH", f"/contacts/{cid}", 200, json={"priority": "HIGH"})
    api("contacts.list", "GET", "/contacts?pageSize=10", 200)
    api("contacts.list.rio", "GET", "/contacts?pageSize=10&format=rio", 200)
    api("contacts.get", "GET", f"/contacts/{cid}", 200)
    api("contacts.get.rio", "GET", f"/contacts/{cid}?format=rio", 200)
    history = api("contacts.messages", "GET", f"/contacts/{cid}/messages", 200)
    api("contacts.messages.rio", "GET", f"/contacts/{cid}/messages?format=rio", 200)
    first_id = history.json()["data"][0]["id"]
    api("contacts.message", "GET", f"/contacts/{cid}/messages/{first_id}", 200)
    api("contacts.message.rio", "GET", f"/contacts/{cid}/messages/{first_id}?format=rio", 200)
    api("contacts.comment", "POST", f"/contacts/{cid}/comments", 201, json={"body": "Internal note"})
    api("channels.list", "GET", "/channels", 200)
    api("templates.list", "GET", "/templates", 200)

    # Deliver before the erase: an erase scrubs the contact out of queued bodies.
    posted.drain(session_factory)
    # Erase last: answers what was erased and fires contact.erased.
    api("contacts.erase", "DELETE", f"/contacts/{cid}", 200)

    counts: Dict[str, int] = {}
    for call in posted.drain(session_factory):
        event = call["headers"]["X-Fx-Event-Type"]
        counts[event] = counts.get(event, 0) + 1
        out[f"webhook.{event}.{counts[event]}"] = normalize(call["content"])
    return out


def _fixture_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def assert_matches_snapshots(out: Dict[str, str]) -> None:
    if UPDATE:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        for old in SNAPSHOT_DIR.glob("*.json"):
            old.unlink()
        for name, body in out.items():
            _fixture_path(name).write_bytes(body.encode("utf-8"))
        return
    expected = sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json"))
    assert expected, f"no snapshots in {SNAPSHOT_DIR}"
    assert sorted(out) == expected, "the set of payloads changed"
    for name in expected:
        want = _fixture_path(name).read_bytes().decode("utf-8")
        assert out[name] == want, f"version 1 payload {name} changed:\nwant {want}\ngot  {out[name]}"


# ── tests ────────────────────────────────────────────────────────────────────
def test_every_event_type_has_a_snapshot(client, session_factory, posted):
    out = run_scenario(client, session_factory, posted)
    events = {name.split(".", 1)[1].rsplit(".", 1)[0] for name in out if name.startswith("webhook.")}
    assert events == set(EVENT_TYPES)


def test_version_1_payloads_are_byte_identical(client, session_factory, posted):
    assert_matches_snapshots(run_scenario(client, session_factory, posted))

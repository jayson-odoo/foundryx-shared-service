"""Gap 5 red tests: ``POST /api/v1/omnichannel/contacts/{identifier}/read``
(UAC documentation/plans/sprint-5/38-gap5-read-acceptance-criteria.md, AC-38-50..62).

Black box only: the HTTP route, database rows, and what crosses the wire to the
provider. The provider is faked at the httpx transport level underneath the REAL
WhatsApp adapter, so method, URL path, headers and the exact JSON body are
asserted. No private helper of the feature is referenced.

Rig notes
- Every wire test uses NON-dev credentials and a configured Meta app (a dev
  credential or an unconfigured app skips the network by design, AC-38-57).
- Every "no provider call" assertion has a control in the same test proving the
  fake counts calls (a real call on another channel, or a call before the state
  change).
- Foreign-tenant rows: primary keys forbid reusing the SAME contact, channel or
  workspace id across tenants, so the foreign rows use their own ids but share
  the workspace id, the phone number and the phone_number_id (no unique index
  under create_all), and foreign MESSAGE rows point at OUR contact id and OUR
  channel id (message rows have no key that forbids it).
"""
import json
import time
import types
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.adapters import meta_graph, whatsapp_cloud
from modules.omnichannel.services import idempotency
from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

FOREIGN_TENANT = "tenant-foreign-gap5"
PHONE = "+60700700701"
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

LOW_ID = "00000000-0000-4000-8000-00000000000a"
HIGH_ID = "ffffffff-ffff-4fff-8fff-fffffffffffb"
SECRET_PROVIDER_TEXT = "ZZ-provider-detail-7f3a"
RECEIPT_KEYS = {"channelId", "messageId", "status"}


def at(minutes=0, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── fake provider at the httpx transport ─────────────────────────────────────
class FakeProvider:
    """Records every request that reaches the (fake) Graph API, keyed by the
    phone number id in the URL path. ``behaviour[pn]`` = ``"ok"`` |
    ``("http", status, message)`` | ``("raise", exc)``."""

    def __init__(self):
        self.calls = []
        self.behaviour = {}
        self.default = "ok"
        self.sleep_on_first = 0.0  # seconds the first call of a phase sleeps
        self._slept = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        segs = request.url.path.strip("/").split("/")
        pn = segs[-2] if len(segs) >= 2 else ""
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            body = None
        self.calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "pn": pn,
                "last": segs[-1],
                "body": body,
                "auth": request.headers.get("authorization"),
                "timeout": dict(request.extensions.get("timeout") or {}),
            }
        )
        if self.sleep_on_first and not self._slept:
            self._slept = True
            time.sleep(self.sleep_on_first)
        action = self.behaviour.get(pn, self.default)
        if action == "ok":
            return httpx.Response(200, json={"success": True})
        if action[0] == "http":
            return httpx.Response(
                action[1], json={"error": {"message": action[2], "code": 100}}
            )
        if action[0] == "body":
            return httpx.Response(action[1], content=action[2])
        if action[0] == "h11":
            # Real HTTP/1.1 request validation, as a live connection does it: an
            # illegal header value raises with the value in the text.
            import h11

            try:
                h11.Request(
                    method=request.method,
                    target=request.url.raw_path,
                    headers=list(request.headers.raw),
                )
            except h11.LocalProtocolError as exc:
                raise httpx.LocalProtocolError(str(exc)) from exc
            return httpx.Response(200, json={"success": True})
        raise action[1]

    def for_pn(self, pn):
        return [c for c in self.calls if c["pn"] == pn]


@pytest.fixture
def provider(monkeypatch):
    prov = FakeProvider()
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    real_client = httpx.Client
    ns = types.SimpleNamespace(
        **{k: getattr(httpx, k) for k in dir(httpx) if not k.startswith("__")}
    )
    ns.Client = lambda *a, **k: real_client(
        transport=httpx.MockTransport(prov.handler), timeout=k.get("timeout", 10.0)
    )
    monkeypatch.setattr(meta_graph, "httpx", ns)
    monkeypatch.setattr(whatsapp_cloud, "httpx", ns)
    return prov


# ── data rig ─────────────────────────────────────────────────────────────────
class Rig:
    def __init__(self, client, sf, provider):
        self.client = client
        self.sf = sf
        self.provider = provider
        self.ws = _default_workspace_id(sf)
        self.hdr = {"Authorization": f"Bearer {_mint(client, self.ws).json()['fullKey']}"}
        self.contact_id = self.contact()

    # contacts
    def contact(self, *, tenant=DEFAULT_TENANT_ID, workspace=None, phone=PHONE):
        from modules.omnichannel.models import Contact
        from modules.omnichannel.services import statuses

        db = self.sf()
        c = Contact(
            tenant_id=tenant,
            workspace_id=workspace or self.ws,
            first_name="Sam",
            phone=phone,
            phone_digits="".join(ch for ch in phone if ch.isdigit()),
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
            priority="MEDIUM",
            csw_expires_at=datetime.now(timezone.utc) + timedelta(hours=20),
        )
        db.add(c)
        db.commit()
        cid = c.id
        db.close()
        return cid

    # channels
    def channel(
        self,
        pn,
        *,
        token=None,
        creds="auto",
        ctype="WHATSAPP",
        tenant=DEFAULT_TENANT_ID,
        workspace=None,
        active=True,
        trashed=False,
        created=0,
        cid=None,
    ):
        from modules.omnichannel.models import Channel
        from modules.omnichannel.security import encrypt_credentials
        from modules.omnichannel.services import statuses

        if creds == "auto":
            creds = encrypt_credentials({"access_token": token or f"tok-{pn}"})
        db = self.sf()
        ch = Channel(
            **({"id": cid} if cid else {}),
            tenant_id=tenant,
            workspace_id=workspace or self.ws,
            channel_type=ctype,
            name=f"ch-{pn}",
            credentials_json=creds,
            phone_number_id=pn if ctype == "WHATSAPP" else None,
            external_account_id=pn if ctype in ("FACEBOOK", "INSTAGRAM") else None,
            is_active=active,
            is_trashed=trashed,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
            created_at=at(created),
        )
        db.add(ch)
        db.commit()
        cid = ch.id
        db.close()
        return cid

    # messages
    def msg(
        self,
        channel_id,
        *,
        wamid="auto",
        when=0,
        sender="CONTACT",
        migrated=None,
        tenant=DEFAULT_TENANT_ID,
        contact_id=None,
        mtype="TEXT",
        created=None,
        metadata=None,
    ):
        from modules.omnichannel.models import ConversationMessage

        if wamid == "auto":
            wamid = f"wamid.{sender.lower()}-{when}-{datetime.now().timestamp()}"
        db = self.sf()
        m = ConversationMessage(
            tenant_id=tenant,
            contact_id=contact_id or self.contact_id,
            channel_id=channel_id,
            sender_type=sender,
            message_type=mtype,
            body="hello",
            external_message_id=wamid,
            delivery_status="DELIVERED" if sender != "CONTACT" else None,
            migrated_from=migrated,
            metadata_json=metadata,
            created_at=created or at(when),
        )
        db.add(m)
        db.commit()
        mid = m.id
        db.close()
        return mid, wamid

    # actions
    def read(self, identifier=None, headers="own"):
        ident = identifier or self.contact_id
        h = self.hdr if headers == "own" else headers
        return self.client.post(f"/api/v1/omnichannel/contacts/{ident}/read", headers=h)

    def receipts(self, resp=None):
        resp = resp or self.read()
        assert resp.status_code == 200, resp.text
        return {r["channelId"]: r for r in resp.json()["receipts"]}

    def unread(self, ident=None):
        r = self.client.get(
            f"/api/v1/omnichannel/contacts/{ident or self.contact_id}", headers=self.hdr
        )
        assert r.status_code == 200, r.text
        return r.json()["unreadCount"]

    def metadata(self, message_id):
        from modules.omnichannel.models import ConversationMessage

        db = self.sf()
        try:
            row = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).one()
            return json.loads(json.dumps(row.metadata_json or {}, sort_keys=True, default=str))
        finally:
            db.close()

    def count(self, model, **flt):
        db = self.sf()
        try:
            q = db.query(model)
            for k, v in flt.items():
                q = q.filter(getattr(model, k) == v)
            return q.count()
        finally:
            db.close()


@pytest.fixture
def rig(client, session_factory, provider):
    return Rig(client, session_factory, provider)


def _fresh_unread(rig):
    """Seed two WhatsApp channels (A older = the workspace's default pick) and one
    customer message on each. Returns (chA, chB, (idA, wamidA), (idB, wamidB))."""
    # Ids are pinned: A has the LOWEST channel id, B the HIGHEST, so a test that
    # fails A (or B) covers the failing channel being first or last under any
    # id, creation or message ordering the implementation might use.
    a = rig.channel("pn-A", token="tok-A", created=0, cid=LOW_ID)
    b = rig.channel("pn-B", token="tok-B", created=10, cid=HIGH_ID)
    ma = rig.msg(a, wamid="wamid.in-A1", when=1)
    mb = rig.msg(b, wamid="wamid.in-B1", when=2)
    return a, b, ma, mb


# ═══ AC-38-50 route, identifier, scoping, auth ═══════════════════════════════
def test_ac50_unknown_contact_is_404_contact_not_found_with_positive_control(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    ok = rig.read()
    assert ok.status_code == 200, ok.text  # the route exists and answers a real contact

    for ident in ("does-not-exist", "id:does-not-exist", "phone:+60700700702"):
        r = rig.read(ident)
        assert r.status_code == 404, (ident, r.text)
        assert r.json()["error"]["code"] == "contact_not_found", (ident, r.text)


def test_ac50_identifier_conventions_resolve_the_same_contact(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    for ident in (rig.contact_id, f"id:{rig.contact_id}", f"phone:{PHONE}"):
        r = rig.read(ident)
        assert r.status_code == 200, (ident, r.text)
        assert r.json()["contactId"] == rig.contact_id


def test_ac50_contact_in_another_workspace_or_tenant_is_404_with_control(rig, session_factory):
    from modules.omnichannel.models import Workspace

    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    assert rig.read().status_code == 200  # control: own contact answers

    db = session_factory()
    ws2 = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second", is_default=False)
    db.add(ws2)
    db.commit()
    ws2_id = ws2.id
    db.close()
    other_ws_contact = rig.contact(workspace=ws2_id, phone="+60700700703")
    foreign_contact = rig.contact(tenant=FOREIGN_TENANT, phone="+60700700704")

    for cid in (other_ws_contact, foreign_contact):
        r = rig.read(cid)
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == "contact_not_found"
    # same phone number as ours but in the foreign tenant: still ours that resolves
    foreign_same_phone = rig.contact(tenant=FOREIGN_TENANT, phone=PHONE)
    r = rig.read(f"phone:{PHONE}")
    assert r.status_code == 200 and r.json()["contactId"] == rig.contact_id
    assert r.json()["contactId"] != foreign_same_phone


@pytest.mark.parametrize("hdr", [None, "Bearer nope", "Bearer fxw_live_deadbeef"])
def test_ac50_missing_or_invalid_key_is_the_uniform_401(rig, hdr):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    assert rig.read().status_code == 200  # control: the real key works
    headers = {"Authorization": hdr} if hdr else {}
    r = rig.read(headers=headers)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_ac50_inactive_module_is_403_service_not_enabled(rig, session_factory):
    from app.services.app_store_service import AppStoreService

    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    assert rig.read().status_code == 200  # control
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    r = rig.read()
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "service_not_enabled"


# ═══ AC-38-51 always 200, unread resets, later message counts again ═════════
def test_ac51_answers_200_shape_and_resets_unread(rig):
    _a, _b, _ma, _mb = _fresh_unread(rig)
    assert rig.unread() == 2  # control: unread is non-zero before the call
    r = rig.read()
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"contactId", "receipts"}
    assert body["contactId"] == rig.contact_id
    assert isinstance(body["receipts"], list)
    assert rig.unread() == 0


def test_ac51_unread_resets_even_when_every_receipt_failed(rig):
    a, b, _ma, _mb = _fresh_unread(rig)
    rig.provider.default = ("http", 400, SECRET_PROVIDER_TEXT)
    assert rig.unread() == 2
    r = rig.read()
    assert r.status_code == 200, r.text
    assert {x["status"] for x in r.json()["receipts"]} == {"failed"}
    assert len(rig.provider.calls) == 2  # control: both were genuinely attempted
    assert rig.unread() == 0


def test_ac51_new_customer_message_after_a_read_counts_as_unread_again(rig):
    a = rig.channel("pn-A")
    rig.msg(a, wamid="wamid.in-1", when=1)
    rig.read()
    assert rig.unread() == 0
    rig.msg(a, wamid="wamid.in-2", created=datetime.now(timezone.utc) + timedelta(seconds=5))
    assert rig.unread() == 1


def test_ac51_a_contact_with_no_messages_still_answers_200_and_zero_unread(rig):
    r = rig.read()
    assert r.status_code == 200, r.text
    assert r.json() == {"contactId": rig.contact_id, "receipts": []}
    assert rig.unread() == 0
    assert rig.provider.calls == []


# ═══ AC-38-52 receipts: one per channel, latest qualifying customer message ═
def test_ac52_one_receipt_per_channel_with_exact_keys_and_ss_message_id(rig):
    a, b, (ida, _wa), (idb, _wb) = _fresh_unread(rig)
    r = rig.read()
    assert r.status_code == 200, r.text
    items = r.json()["receipts"]
    assert len(items) == 2
    for it in items:
        assert set(it) == RECEIPT_KEYS
    by_channel = {i["channelId"]: i for i in items}
    assert set(by_channel) == {a, b}
    assert by_channel[a]["messageId"] == ida and by_channel[b]["messageId"] == idb
    # messageId is the SS id exposed as MessageItem.id
    listed = rig.client.get(
        f"/api/v1/omnichannel/contacts/{rig.contact_id}/messages", headers=rig.hdr
    ).json()["data"]
    assert {m["id"] for m in listed} >= {ida, idb}
    assert len(rig.provider.calls) == 2  # the fake saw both


def test_ac52_latest_customer_message_wins_and_older_ones_are_not_targeted(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.old", when=1)
    new_id, new_wamid = rig.msg(ch, wamid="wamid.new", when=5)
    rig.msg(ch, wamid="wamid.mid", when=3)
    got = rig.receipts()
    assert got[ch]["messageId"] == new_id
    calls = rig.provider.for_pn("pn-A")
    assert len(calls) == 1 and calls[0]["body"]["message_id"] == new_wamid


def test_ac52_tie_on_created_at_resolves_to_the_greater_id(rig):
    # Reading: same rule as the thread preview (contact_repository sorts by id
    # descending on a created_at tie). UAC only says "deterministic".
    ch = rig.channel("pn-A")
    m1 = rig.msg(ch, wamid="wamid.tie-1", when=4)
    m2 = rig.msg(ch, wamid="wamid.tie-2", when=4)
    winner = max(m1[0], m2[0])
    assert rig.receipts()[ch]["messageId"] == winner
    sent = rig.provider.for_pn("pn-A")[0]["body"]["message_id"]
    assert sent == (m1[1] if winner == m1[0] else m2[1])


def test_ac52_agent_system_and_note_rows_newer_than_the_customer_are_ignored(rig):
    ch = rig.channel("pn-A")
    cust_id, cust_wamid = rig.msg(ch, wamid="wamid.cust", when=1)
    rig.msg(ch, wamid="wamid.agent", when=5, sender="AGENT")
    rig.msg(ch, wamid="wamid.system", when=6, sender="SYSTEM")
    rig.msg(ch, wamid=None, when=7, sender="SYSTEM", mtype="NOTE")
    got = rig.receipts()
    assert got[ch]["messageId"] == cust_id
    assert [c["body"]["message_id"] for c in rig.provider.for_pn("pn-A")] == [cust_wamid]


def test_ac52_only_agent_system_rows_means_empty_receipts_with_control(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.agent", when=5, sender="AGENT")
    rig.msg(ch, wamid=None, when=7, sender="SYSTEM", mtype="NOTE")
    r = rig.read()
    assert r.status_code == 200 and r.json()["receipts"] == []
    assert rig.provider.calls == []
    # control: a qualifying customer message makes the same rig call out
    rig.msg(ch, wamid="wamid.cust", when=9)
    assert len(rig.receipts()) == 1
    assert len(rig.provider.calls) == 1


def test_ac52_newest_customer_row_without_provider_id_falls_back_to_older(rig):
    ch = rig.channel("pn-A")
    older_id, older_wamid = rig.msg(ch, wamid="wamid.older", when=1)
    rig.msg(ch, wamid=None, when=5)
    got = rig.receipts()
    assert got[ch]["messageId"] == older_id
    assert [c["body"]["message_id"] for c in rig.provider.for_pn("pn-A")] == [older_wamid]


def test_ac52_newest_imported_customer_row_falls_back_to_older(rig):
    ch = rig.channel("pn-A")
    older_id, older_wamid = rig.msg(ch, wamid="wamid.native", when=1)
    rig.msg(ch, wamid="wamid.imported", when=5, migrated="respondio")
    got = rig.receipts()
    assert got[ch]["messageId"] == older_id
    assert [c["body"]["message_id"] for c in rig.provider.for_pn("pn-A")] == [older_wamid]


def test_ac52_only_imported_or_idless_rows_means_no_receipt_for_the_channel(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.imported", when=5, migrated="respondio")
    rig.msg(ch, wamid=None, when=6)
    r = rig.read()
    assert r.status_code == 200 and r.json()["receipts"] == []
    assert rig.provider.calls == []


def test_ac52_null_channel_id_is_skipped(rig):
    ch = rig.channel("pn-A")
    on_ch_id, on_ch_wamid = rig.msg(ch, wamid="wamid.on-channel", when=1)
    rig.msg(None, wamid="wamid.no-channel", when=9)
    r = rig.read()
    assert r.status_code == 200, r.text
    assert [x["messageId"] for x in r.json()["receipts"]] == [on_ch_id]
    assert [c["body"]["message_id"] for c in rig.provider.calls] == [on_ch_wamid]


def test_ac52_channels_the_contact_never_wrote_on_get_no_receipt(rig):
    a = rig.channel("pn-A")
    rig.channel("pn-quiet", created=5)
    rig.msg(a, wamid="wamid.in-1", when=1)
    r = rig.read()
    assert [x["channelId"] for x in r.json()["receipts"]] == [a]
    assert len(rig.provider.calls) == 1 and rig.provider.calls[0]["pn"] == "pn-A"


# ═══ AC-38-53 the WhatsApp wire call ═════════════════════════════════════════
def test_ac53_provider_call_is_exactly_the_read_status_post(rig):
    ch = rig.channel("pn-A", token="tok-A-secret")
    _mid, wamid = rig.msg(ch, wamid="wamid.in-1", when=1)
    got = rig.receipts()
    assert got[ch]["status"] == "sent"
    assert len(rig.provider.calls) == 1, "the fake provider was never hit"
    call = rig.provider.calls[0]
    assert call["method"] == "POST"
    assert call["path"].endswith("/pn-A/messages")
    assert call["last"] == "messages" and call["pn"] == "pn-A"
    assert call["body"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wamid,
    }
    assert call["auth"] == "Bearer tok-A-secret"


def test_ac53_each_channel_uses_its_own_number_and_credentials_never_the_default(rig):
    a, b, (_ia, wa), (_ib, wb) = _fresh_unread(rig)  # A is the older, default-pick channel
    rig.receipts()
    by_pn = {c["pn"]: c for c in rig.provider.calls}
    assert set(by_pn) == {"pn-A", "pn-B"}
    assert by_pn["pn-A"]["auth"] == "Bearer tok-A" and by_pn["pn-A"]["body"]["message_id"] == wa
    assert by_pn["pn-B"]["auth"] == "Bearer tok-B" and by_pn["pn-B"]["body"]["message_id"] == wb


def test_ac53_customer_wrote_only_on_the_second_number_so_the_first_is_never_called(rig):
    rig.channel("pn-A", token="tok-A", created=0)  # workspace default pick, silent
    b = rig.channel("pn-B", token="tok-B", created=10)
    _id, wamid = rig.msg(b, wamid="wamid.in-B", when=1)
    rig.receipts()
    assert [(c["pn"], c["auth"]) for c in rig.provider.calls] == [("pn-B", "Bearer tok-B")]
    assert rig.provider.calls[0]["body"]["message_id"] == wamid


def test_ac53_provider_200_gives_sent(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    assert rig.receipts()[ch]["status"] == "sent"
    assert len(rig.provider.calls) == 1


# ═══ AC-38-54 idempotence, independence, marker never exposed ═══════════════
def test_ac54_repeat_with_no_new_message_is_already_sent_and_makes_no_call(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    first = rig.receipts()
    assert first[ch]["status"] == "sent" and len(rig.provider.calls) == 1  # control
    second = rig.receipts()
    assert second[ch]["status"] == "already_sent"
    assert second[ch]["messageId"] == first[ch]["messageId"]
    assert len(rig.provider.calls) == 1


def test_ac54_a_new_customer_message_makes_a_new_call_on_the_new_provider_id(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    rig.receipts()
    new_id, new_wamid = rig.msg(ch, wamid="wamid.in-2", when=9)
    got = rig.receipts()
    assert got[ch]["status"] == "sent" and got[ch]["messageId"] == new_id
    assert [c["body"]["message_id"] for c in rig.provider.calls] == ["wamid.in-1", "wamid.in-2"]
    assert rig.receipts()[ch]["status"] == "already_sent"
    assert len(rig.provider.calls) == 2


def test_ac54_channels_are_independent_repeat_calls_only_the_failed_one(rig):
    a, b, _ma, _mb = _fresh_unread(rig)
    rig.provider.behaviour["pn-A"] = ("http", 500, SECRET_PROVIDER_TEXT)
    first = rig.receipts()
    assert first[a]["status"] == "failed" and first[b]["status"] == "sent"
    assert len(rig.provider.for_pn("pn-A")) == 1 and len(rig.provider.for_pn("pn-B")) == 1
    rig.provider.behaviour["pn-A"] = "ok"
    second = rig.receipts()
    assert second[a]["status"] == "sent" and second[b]["status"] == "already_sent"
    assert len(rig.provider.for_pn("pn-A")) == 2
    assert len(rig.provider.for_pn("pn-B")) == 1


def test_ac54_marker_is_stored_on_a_sent_target_and_not_on_a_failed_one(rig):
    # Reading of the build note (marker lives in the target's metadata_json).
    a, b, (ida, _wa), (idb, _wb) = _fresh_unread(rig)
    before_a, before_b = rig.metadata(ida), rig.metadata(idb)
    rig.provider.behaviour["pn-B"] = ("http", 400, SECRET_PROVIDER_TEXT)
    got = rig.receipts()
    assert got[a]["status"] == "sent" and got[b]["status"] == "failed"
    assert rig.metadata(ida) != before_a, "control: a sent target carries a marker"
    assert rig.metadata(idb) == before_b, "a failed target must not carry a marker"


def test_ac54_marker_appears_in_no_read_shape(rig):
    ch = rig.channel("pn-A")
    mid, _w = rig.msg(ch, wamid="wamid.in-1", when=1)
    base = f"/api/v1/omnichannel/contacts/{rig.contact_id}/messages"
    urls = [
        base,
        f"{base}?format=rio",
        f"{base}/{mid}",
        f"{base}/{mid}?format=rio",
        f"/api/v1/omnichannel/contacts/{rig.contact_id}",
        f"/api/v1/omnichannel/contacts/{rig.contact_id}?format=rio",
    ]
    before_meta = rig.metadata(mid)
    before = {u: rig.client.get(u, headers=rig.hdr) for u in urls}
    for u, resp in before.items():
        assert resp.status_code == 200, (u, resp.text)
    assert rig.receipts()[ch]["status"] == "sent"
    after_meta = rig.metadata(mid)
    assert after_meta != before_meta, "control: a marker was written"
    added = {k: v for k, v in after_meta.items() if before_meta.get(k) != v}
    for u in urls:
        resp = rig.client.get(u, headers=rig.hdr)
        assert resp.status_code == 200
        before_json = before[u].json()
        after_json = resp.json()
        # unread legitimately changes on the contact routes; compare the rest
        if "unreadCount" in after_json:
            before_json = {**before_json, "unreadCount": after_json["unreadCount"]}
        assert after_json == before_json, f"{u} changed after a read"
        for key, val in added.items():
            assert key not in resp.text, f"marker key {key!r} appears on {u}"
            if isinstance(val, str) and val:
                assert val not in resp.text, f"marker value appears on {u}"


# ═══ AC-38-55 failure per channel ═══════════════════════════════════════════
FAILURES = {
    "provider_4xx": ("http", 400, SECRET_PROVIDER_TEXT),
    "provider_5xx": ("http", 503, SECRET_PROVIDER_TEXT),
    "transport_error": ("raise", httpx.ConnectError(SECRET_PROVIDER_TEXT)),
    "unexpected_adapter_exception": ("raise", RuntimeError(SECRET_PROVIDER_TEXT)),
}


@pytest.mark.parametrize("fail_first", [True, False])
@pytest.mark.parametrize("cause", sorted(FAILURES))
def test_ac55_failure_is_per_channel_hidden_and_retried(rig, cause, fail_first):
    a, b, (ida, _wa), (idb, _wb) = _fresh_unread(rig)
    bad, good = ("pn-A", "pn-B") if fail_first else ("pn-B", "pn-A")
    bad_ch, good_ch = (a, b) if fail_first else (b, a)
    bad_id = ida if fail_first else idb
    rig.provider.behaviour[bad] = FAILURES[cause]
    meta_before = rig.metadata(bad_id)

    r = rig.read()
    assert r.status_code == 200, r.text
    assert SECRET_PROVIDER_TEXT not in r.text, "provider text reached the response"
    got = {x["channelId"]: x for x in r.json()["receipts"]}
    assert got[bad_ch]["status"] == "failed"
    assert got[good_ch]["status"] == "sent"  # other channel still attempted
    assert len(rig.provider.for_pn(good)) == 1  # control: the fake counts calls
    assert len(rig.provider.for_pn(bad)) == 1
    assert rig.metadata(bad_id) == meta_before, "no marker on a failure"
    assert rig.unread() == 0

    rig.provider.behaviour[bad] = "ok"
    again = rig.receipts()
    assert again[bad_ch]["status"] == "sent", "the next call must try again"
    assert again[good_ch]["status"] == "already_sent"
    assert len(rig.provider.for_pn(bad)) == 2
    assert len(rig.provider.for_pn(good)) == 1


@pytest.mark.parametrize("fail_first", [True, False])
def test_ac55_unreadable_credentials_fail_that_channel_only_and_retry_after_repair(
    rig, session_factory, fail_first
):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials

    # a = the unreadable channel. fail_first=True: it is pn-A with the LOWEST id;
    # fail_first=False: it is pn-B with the HIGHEST id (readable one is the other).
    blob = "not-a-valid-credential-blob"
    if fail_first:
        a = rig.channel("pn-A", creds=blob, created=0, cid=LOW_ID)
        b = rig.channel("pn-B", token="tok-B", created=10, cid=HIGH_ID)
        bad_pn, good_pn = "pn-A", "pn-B"
    else:
        b = rig.channel("pn-A", token="tok-A", created=0, cid=LOW_ID)
        a = rig.channel("pn-B", creds=blob, created=10, cid=HIGH_ID)
        bad_pn, good_pn = "pn-B", "pn-A"
    rig.msg(a, wamid="wamid.in-bad", when=1 if fail_first else 2)
    rig.msg(b, wamid="wamid.in-good", when=2 if fail_first else 1)

    r = rig.read()
    assert r.status_code == 200, r.text
    got = {x["channelId"]: x for x in r.json()["receipts"]}
    assert got[a]["status"] == "failed"
    assert got[b]["status"] == "sent"
    assert len(rig.provider.for_pn(good_pn)) == 1  # control
    assert rig.provider.for_pn(bad_pn) == []
    assert rig.unread() == 0

    db = session_factory()
    db.query(Channel).filter(Channel.id == a).update(
        {"credentials_json": encrypt_credentials({"access_token": "tok-fixed"})}
    )
    db.commit()
    db.close()
    again = rig.receipts()
    assert again[a]["status"] == "sent" and again[b]["status"] == "already_sent"
    assert len(rig.provider.for_pn(bad_pn)) == 1


# ═══ AC-38-56 unavailable channels, foreign channels ════════════════════════
@pytest.mark.parametrize(
    "state", [{"active": False}, {"trashed": True}, {"active": False, "trashed": True}]
)
def test_ac56_paused_or_disconnected_channel_is_unavailable_with_no_call(rig, state):
    live = rig.channel("pn-live", token="tok-live", created=0)
    dead = rig.channel("pn-dead", token="tok-dead", created=10, **state)
    rig.msg(live, wamid="wamid.in-live", when=1)
    rig.msg(dead, wamid="wamid.in-dead", when=2)
    got = rig.receipts()
    assert got[dead]["status"] == "channel_unavailable"
    assert set(got[dead]) == RECEIPT_KEYS
    assert got[live]["status"] == "sent"
    assert len(rig.provider.for_pn("pn-live")) == 1  # control
    assert rig.provider.for_pn("pn-dead") == []
    assert rig.unread() == 0


def test_ac56_channel_in_another_workspace_of_the_same_tenant_is_left_out(rig, session_factory):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws2 = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second", is_default=False)
    db.add(ws2)
    db.commit()
    ws2_id = ws2.id
    db.close()
    mine = rig.channel("pn-mine", token="tok-mine", created=0)
    elsewhere = rig.channel("pn-elsewhere", token="tok-else", workspace=ws2_id, created=5)
    rig.msg(mine, wamid="wamid.in-mine", when=1)
    rig.msg(elsewhere, wamid="wamid.in-else", when=2)
    r = rig.read()
    assert r.status_code == 200, r.text
    ids = [x["channelId"] for x in r.json()["receipts"]]
    assert ids == [mine], "a channel of another workspace must be left out"
    assert len(rig.provider.for_pn("pn-mine")) == 1  # control
    assert rig.provider.for_pn("pn-elsewhere") == []


def test_ac56_channel_row_of_another_tenant_is_never_used_and_left_out(rig):
    mine = rig.channel("pn-mine", token="tok-mine", created=0)
    foreign = rig.channel("pn-foreign", token="tok-foreign", tenant=FOREIGN_TENANT, created=5)
    rig.msg(mine, wamid="wamid.in-mine", when=1)
    # a message of ours that points at the foreign channel row
    rig.msg(foreign, wamid="wamid.in-foreign", when=2)
    r = rig.read()
    assert r.status_code == 200, r.text
    assert [x["channelId"] for x in r.json()["receipts"]] == [mine]
    assert len(rig.provider.for_pn("pn-mine")) == 1  # control
    assert rig.provider.for_pn("pn-foreign") == []


# ═══ AC-38-57 unsupported types, dev credentials, unconfigured app ══════════
@pytest.mark.parametrize("ctype", ["FACEBOOK", "INSTAGRAM", "WEBCHAT"])
def test_ac57_non_whatsapp_channels_are_not_supported_with_no_call(rig, ctype):
    wa = rig.channel("pn-wa", token="tok-wa", created=0)
    other = rig.channel("ext-1", token="tok-x", ctype=ctype, created=5)
    rig.msg(wa, wamid="wamid.in-wa", when=1)
    rig.msg(other, wamid="mid.in-other", when=2)
    got = rig.receipts()
    assert got[other]["status"] == "not_supported"
    assert got[wa]["status"] == "sent"
    assert len(rig.provider.calls) == 1 and rig.provider.calls[0]["pn"] == "pn-wa"  # control
    assert rig.unread() == 0


def test_ac57_dev_credentials_make_no_network_call_and_answer_sent(rig):
    from modules.omnichannel.security import encrypt_credentials

    dev = rig.channel("pn-dev", creds=encrypt_credentials({"dev": True}), created=0)
    real = rig.channel("pn-real", token="tok-real", created=5)
    rig.msg(dev, wamid="wamid.in-dev", when=1)
    rig.msg(real, wamid="wamid.in-real", when=2)
    got = rig.receipts()
    assert got[dev]["status"] == "sent"
    assert got[real]["status"] == "sent"
    assert len(rig.provider.for_pn("pn-real")) == 1  # control: the fake counts
    assert rig.provider.for_pn("pn-dev") == []


def test_ac57_unconfigured_app_makes_no_network_call_and_answers_sent(rig, monkeypatch):
    ch = rig.channel("pn-A", token="tok-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    assert rig.receipts()[ch]["status"] == "sent"
    assert rig.provider.calls == []
    # control: once the app is configured the same rig does see a new message's call
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    rig.msg(ch, wamid="wamid.in-2", when=5)
    assert rig.receipts()[ch]["status"] == "sent"
    assert len(rig.provider.calls) == 1


# ═══ AC-38-58 unread reset committed before the first provider call ═════════
class _TxnTracker:
    """Tracks every Session that begins a transaction while armed; at provider
    time none of them may still be in a transaction (committed or rolled back)."""

    def __init__(self):
        self.sessions = []
        self.armed = False

    def on_begin(self, session, transaction, connection):
        if self.armed and session not in self.sessions:
            self.sessions.append(session)

    def open_now(self):
        return [s for s in self.sessions if s.in_transaction()]


@pytest.fixture
def txn_tracker():
    tracker = _TxnTracker()
    event.listen(Session, "after_begin", tracker.on_begin)
    yield tracker
    event.remove(Session, "after_begin", tracker.on_begin)


def test_ac58_tracker_control_sees_an_open_transaction(session_factory, txn_tracker):
    """Control: the instrument reports an open transaction when there is one."""
    from modules.omnichannel.models import Contact

    txn_tracker.armed = True
    db = session_factory()
    db.query(Contact).first()
    assert txn_tracker.open_now(), "tracker cannot see an open transaction"
    db.commit()
    assert txn_tracker.open_now() == []
    db.close()


def test_ac58_reset_is_committed_and_no_transaction_is_open_during_the_provider_call(
    rig, provider, txn_tracker
):
    """sqlite rig limit: the suite runs every session on ONE StaticPool
    connection, so a "separate session" sees uncommitted rows and cannot prove
    commit ordering. This test instead proves (a) no tracked Session is inside a
    transaction when the provider is called (so nothing is pending or held open)
    and (b) the reset is already stored at that moment."""
    from modules.omnichannel.models import Contact

    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    seen = []
    original = provider.handler

    def spying_handler(request):
        db = rig.sf()
        try:
            read_at = db.query(Contact.agent_last_read_at).filter(
                Contact.id == rig.contact_id
            ).scalar()
        finally:
            db.close()
        seen.append({"read_at": read_at, "open": list(txn_tracker.open_now())})
        return original(request)

    # control: before the call the reset is genuinely absent
    db = rig.sf()
    assert db.query(Contact.agent_last_read_at).filter(Contact.id == rig.contact_id).scalar() is None
    db.close()

    real_client = httpx.Client
    ns = meta_graph.httpx
    ns.Client = lambda *a, **k: real_client(
        transport=httpx.MockTransport(spying_handler), timeout=10.0
    )
    txn_tracker.armed = True
    r = rig.read()
    txn_tracker.armed = False
    assert r.status_code == 200, r.text
    assert len(seen) == 1, "provider was not called"
    assert seen[0]["read_at"] is not None, "reset not stored before the provider call"
    assert seen[0]["open"] == [], "a database transaction was open across the provider call"


# ═══ AC-38-59 activity log ═══════════════════════════════════════════════════
def _activity(session_factory, tenant=DEFAULT_TENANT_ID):
    from app.models.integration_activity import SOURCE_OUTBOUND_META, IntegrationActivity

    db = session_factory()
    try:
        rows = (
            db.query(IntegrationActivity)
            .filter(
                IntegrationActivity.tenant_id == tenant,
                IntegrationActivity.source == SOURCE_OUTBOUND_META,
            )
            .order_by(IntegrationActivity.created_at.asc())
            .all()
        )
        return [
            {c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows
        ]
    finally:
        db.close()


def test_ac59_each_provider_call_is_recorded_without_any_token(rig, session_factory):
    a, b, _ma, _mb = _fresh_unread(rig)
    rig.provider.behaviour["pn-B"] = ("http", 400, SECRET_PROVIDER_TEXT)
    assert _activity(session_factory) == []  # control: nothing recorded yet
    got = rig.receipts()
    assert got[a]["status"] == "sent" and got[b]["status"] == "failed"
    assert len(rig.provider.calls) == 2
    rows = _activity(session_factory)
    assert len(rows) == 2, "one outbound_meta record per provider call"
    assert sorted(r["status"] for r in rows) == ["error", "success"]
    for r in rows:
        assert r["operation"].startswith("graph:")
        assert r["operation"] != "graph:send", "a read has its own label"
        assert r["workspace_id"] == rig.ws
    blob = json.dumps(rows, default=str)
    assert "tok-A" not in blob and "tok-B" not in blob
    assert "Bearer" not in blob


def test_ac59_no_provider_call_means_no_record(rig, session_factory):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    rig.receipts()
    assert len(_activity(session_factory)) == 1  # control: a call is recorded
    rig.receipts()  # already_sent: no call
    assert len(rig.provider.calls) == 1
    assert len(_activity(session_factory)) == 1


# ═══ AC-38-60 no message row, no webhook, no workflow trigger ═══════════════
def _publish_workflow(session_factory, trigger_type, config=None):
    from app.services.workflow_service import WorkflowService

    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": trigger_type, "config": config or {}},
            {
                "id": "get_1",
                "kind": "action",
                "type": "omnichannel.get_contact",
                "config": {"contactId": "{{ trigger.contact.id }}"},
            },
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "get_1"}],
    }
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(
            DEFAULT_TENANT_ID, name=f"gap5 {trigger_type}", description="", draft=doc, actor_id=None
        )
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        return wf.id
    finally:
        db.close()


def _runs(rig, wf_id):
    from app.models.workflow import WorkflowRun

    return rig.count(WorkflowRun, workflow_id=wf_id)


def test_ac60_creates_no_message_row_and_fires_no_webhook_or_workflow_run(
    rig, monkeypatch, session_factory
):
    import fakeredis

    import modules.omnichannel.services.webhook_delivery as wd
    from app.models.workflow import WorkflowRun
    from modules.omnichannel.models import ConversationMessage, WebhookDelivery
    from modules.omnichannel.services import realtime
    from tests.test_omnichannel_webhooks import _process, _wa_payload

    realtime.set_client(fakeredis.FakeRedis(decode_responses=True))
    try:
        # keep the delivery worker off the network; rows are what we observe
        monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: httpx.Response(200))
        a, b, _ma, _mb = _fresh_unread(rig)
        reg = rig.client.post(
            "/api/v1/omnichannel/webhooks",
            json={
                "name": "w",
                "url": "https://hooks.example.com/w",
                "events": ["message.inbound", "message.status", "contact.updated", "message.reaction"],
            },
            headers=rig.hdr,
        )
        assert reg.status_code == 201, reg.text

        # Published workflows on the inbound-message trigger and on contact-change
        # triggers (conversation opened/closed, field changed, lifecycle changed).
        from modules.omnichannel.models import ContactField

        db = session_factory()
        db.add(ContactField(tenant_id=DEFAULT_TENANT_ID, workspace_id=rig.ws,
                            key="gap5", label="Gap5", type="text"))
        db.commit()
        db.close()
        wf_received = _publish_workflow(session_factory, "omnichannel.message_received")
        wf_opened = _publish_workflow(session_factory, "omnichannel.conversation_opened")
        wf_closed = _publish_workflow(session_factory, "omnichannel.conversation_closed")
        wf_field = _publish_workflow(
            session_factory, "omnichannel.contact_field_changed", {"fieldKey": "gap5"}
        )
        wf_life = _publish_workflow(session_factory, "omnichannel.lifecycle_changed")
        watched = [wf_received, wf_opened, wf_closed, wf_field, wf_life]

        # Positive control: a real inbound through the normal path makes the
        # message_received and conversation_opened workflows run.
        deliveries_start = rig.count(WebhookDelivery)
        _process(
            session_factory,
            a,
            _wa_payload(wamid="wamid.ctl-1", from_="60700700799", text="control"),
        )
        assert rig.count(WebhookDelivery) > deliveries_start, (
            "control: the first inbound event made no delivery row"
        )
        assert _runs(rig, wf_received) == 1, "control: message_received did not fire"
        assert _runs(rig, wf_opened) == 1, "control: conversation_opened did not fire"
        # Positive control for a contact-change trigger: a real field change.
        rig.client.patch(
            f"/api/v1/omnichannel/contacts/{rig.contact_id}",
            json={"customFields": {"gap5": "x"}},
            headers=rig.hdr,
        )
        assert _runs(rig, wf_field) >= 1, "control: contact_field_changed did not fire"

        messages_before = rig.count(ConversationMessage)
        deliveries_before = rig.count(WebhookDelivery)
        runs_before = {w: _runs(rig, w) for w in watched}
        total_runs_before = rig.count(WorkflowRun)
        calls_before = len(rig.provider.calls)

        r = rig.read()
        assert r.status_code == 200 and len(r.json()["receipts"]) >= 2
        assert len(rig.provider.calls) > calls_before

        assert rig.count(ConversationMessage) == messages_before
        assert rig.count(WebhookDelivery) == deliveries_before
        assert {w: _runs(rig, w) for w in watched} == runs_before
        assert rig.count(WorkflowRun) == total_runs_before

        # control: a second real inbound on the endpoint's own channel still
        # records a delivery row after the read
        _process(
            session_factory,
            a,
            _wa_payload(wamid="wamid.ctl-2", from_="60700700799", text="control two"),
        )
        assert rig.count(WebhookDelivery) > deliveries_before
    finally:
        realtime.set_client(None)


# ═══ AC-38-61 tenant scope ═══════════════════════════════════════════════════
def test_ac61_foreign_rows_sharing_our_ids_change_nothing_and_get_no_call(rig):
    mine = rig.channel("pn-shared", token="tok-mine", created=0)
    mine_msg, mine_wamid = rig.msg(mine, wamid="wamid.mine-1", when=1)
    # Foreign rows. Primary keys forbid reusing our contact/channel/workspace id as
    # a row id, so: same workspace id + same phone + same phone_number_id on the
    # foreign contact/channel, and foreign MESSAGE rows that point at OUR contact
    # id and OUR channel id and are NEWER than ours.
    foreign_contact = rig.contact(tenant=FOREIGN_TENANT, phone=PHONE)
    foreign_channel = rig.channel("pn-shared", token="tok-foreign", tenant=FOREIGN_TENANT, created=5)
    rig.msg(mine, wamid="wamid.foreign-on-ours", when=9, tenant=FOREIGN_TENANT)
    rig.msg(foreign_channel, wamid="wamid.foreign-1", when=9, tenant=FOREIGN_TENANT,
            contact_id=foreign_contact)
    rig.msg(foreign_channel, wamid="wamid.foreign-2", when=9, tenant=FOREIGN_TENANT)

    r = rig.read(f"phone:{PHONE}")
    assert r.status_code == 200, r.text
    assert r.json()["contactId"] == rig.contact_id
    items = r.json()["receipts"]
    assert [(i["channelId"], i["messageId"]) for i in items] == [(mine, mine_msg)]
    calls = rig.provider.calls
    assert len(calls) == 1  # control: the fake counts, and only ours was sent
    assert calls[0]["body"]["message_id"] == mine_wamid
    assert calls[0]["auth"] == "Bearer tok-mine"


def test_ac61_foreign_customer_messages_do_not_count_as_unread_or_move_state(rig):
    from modules.omnichannel.models import Contact

    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.mine", when=1)
    foreign_contact = rig.contact(tenant=FOREIGN_TENANT, phone="+60700700705")
    rig.msg(ch, wamid="wamid.foreign-new", when=9, tenant=FOREIGN_TENANT, contact_id=foreign_contact)
    db = rig.sf()
    before = db.query(Contact.agent_last_read_at).filter(Contact.id == foreign_contact).scalar()
    db.close()
    assert before is None
    rig.read()
    db = rig.sf()
    after = db.query(Contact.agent_last_read_at).filter(Contact.id == foreign_contact).scalar()
    mine = db.query(Contact.agent_last_read_at).filter(Contact.id == rig.contact_id).scalar()
    db.close()
    assert mine is not None, "control: our contact was marked read"
    assert after is None, "a foreign tenant's contact must not change"
    assert len(rig.provider.calls) == 1


# ═══ AC-38-62 consumer guide ═════════════════════════════════════════════════
GUIDE = "documentation/omnichannel/consumer-integration-guide.md"
ROUTE = "/api/v1/omnichannel/contacts/{identifier}/read"


def _guide():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    return (root / GUIDE).read_text(encoding="utf-8")


def _section(text, start_marker, end_marker):
    start = text.index(start_marker)
    end = text.index(end_marker, start + len(start_marker))
    return text[start:end]


def test_ac62_guide_documents_the_route_in_section_6a_with_every_status():
    text = _guide()
    s6a = _section(text, "## 6a. Contacts & conversations", "## 6b.")
    assert ROUTE in s6a
    for status in ("sent", "already_sent", "failed", "channel_unavailable", "not_supported"):
        assert f"`{status}`" in s6a, f"status {status} missing from section 6a"
    idx = s6a.index(ROUTE)
    assert "POST" in s6a[max(0, idx - 80): idx]
    low = s6a.lower()
    assert "safe to call again" in low or "safe to retry" in low
    assert "only" in low and "read receipt" in low


def test_ac62_guide_states_that_only_this_route_sends_a_read_receipt():
    text = _guide()
    s6a = _section(text, "## 6a. Contacts & conversations", "## 6b.").lower()
    assert "only this route" in s6a or "only this endpoint" in s6a


def test_ac62_appendix_index_has_the_route_beside_the_comments_row():
    text = _guide()
    appendix = text[text.index("## Appendix - quick endpoint index"):]
    lines = appendix.splitlines()
    comments = next(i for i, ln in enumerate(lines) if "/contacts/{identifier}/comments" in ln)
    read_rows = [i for i, ln in enumerate(lines) if ROUTE in ln and ln.lstrip().startswith("|")]
    assert read_rows, "no appendix index row for the read route"
    assert min(abs(i - comments) for i in read_rows) <= 1, "row is not beside the /comments row"
    row = lines[read_rows[0]]
    assert "POST" in row


def test_ac62_changelog_has_a_row_for_the_read_route():
    text = _guide()
    head = text[: text.index("## 1. The big picture")]
    assert "read" in head.lower()
    rows = [
        ln for ln in head.splitlines() if ln.lstrip().lstrip(">").lstrip().startswith("|")
    ]
    assert any(
        ("/read" in ln or "read receipt" in ln.lower()) for ln in rows
    ), "no changelog row mentions the read route"


# ═══ Review round, group A: rules added after the first green run ═══════════
FAKE_TOKEN = "FAKE-tok-9f2c1d"
TOKEN_FRAGMENT = "9f2c1d"


def _everything_stored(session_factory):
    """Every column of every activity row of the default tenant, as one string."""
    from app.models.integration_activity import IntegrationActivity

    db = session_factory()
    try:
        rows = db.query(IntegrationActivity).filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID
        ).all()
        return json.dumps(
            [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows],
            default=str,
        )
    finally:
        db.close()


# AC-38-59: no token in the record or the response, whatever the error text says
@pytest.mark.parametrize(
    "cause",
    ["provider_text_with_token", "transport_text_with_token", "illegal_header_value"],
)
def test_ac59_no_token_in_the_activity_record_or_the_response(rig, session_factory, cause):
    token = "FAKE-tok\n9f2c1d" if cause == "illegal_header_value" else FAKE_TOKEN
    ch = rig.channel("pn-A", token=token)
    rig.msg(ch, wamid="wamid.in-1", when=1)
    rig.provider.behaviour["pn-A"] = {
        "provider_text_with_token": ("http", 400, f"Malformed access token {FAKE_TOKEN}"),
        "transport_text_with_token": ("raise", httpx.ConnectError(f"no route using {FAKE_TOKEN}")),
        "illegal_header_value": ("h11",),
    }[cause]
    r = rig.read()
    assert r.status_code == 200, r.text
    assert r.json()["receipts"][0]["status"] == "failed"
    assert len(rig.provider.calls) == 1, "the fake was never reached"
    stored = _everything_stored(session_factory)
    # control: the call WAS recorded, so the absence below is about content
    rows = _activity(session_factory)
    assert len(rows) == 1 and rows[0]["status"] == "error"
    assert TOKEN_FRAGMENT not in stored, "token text found in the activity record"
    assert TOKEN_FRAGMENT not in r.text
    assert "FAKE-tok" not in stored and "FAKE-tok" not in r.text


# AC-38-59: the record carries the target's provider id and the HTTP status
def test_ac59_activity_row_has_provider_id_reference_and_http_status(rig, session_factory):
    a, b, (_ia, wa), (_ib, wb) = _fresh_unread(rig)
    rig.provider.behaviour["pn-B"] = ("http", 400, SECRET_PROVIDER_TEXT)
    rig.receipts()
    rows = {r["external_ref"]: r for r in _activity(session_factory)}
    assert set(rows) == {wa, wb}, "reference must be the target's provider id"
    assert rows[wa]["status"] == "success" and rows[wa]["status_code"] == 200
    assert rows[wb]["status"] == "error" and rows[wb]["status_code"] == 400


# AC-38-53: a 200 that is not {"success": true} is a refusal
BAD_200_BODIES = {
    "success_false": b'{"success": false}',
    "empty_object": b"{}",
    "error_object": b'{"error": {"code": 4}}',
    "not_json": b"<html>ok</html>",
    "json_array": b"[1]",
}


@pytest.mark.parametrize("name", sorted(BAD_200_BODIES))
def test_ac53_a_200_without_success_true_fails_stores_no_marker_and_retries(rig, name):
    ch = rig.channel("pn-A")
    mid, _w = rig.msg(ch, wamid="wamid.in-1", when=1)
    before = rig.metadata(mid)
    rig.provider.behaviour["pn-A"] = ("body", 200, BAD_200_BODIES[name])
    got = rig.receipts()
    assert got[ch]["status"] == "failed"
    assert len(rig.provider.calls) == 1, "the fake was never reached"
    assert rig.metadata(mid) == before, "no marker on a refused receipt"
    rig.provider.behaviour["pn-A"] = "ok"
    again = rig.receipts()
    assert again[ch]["status"] == "sent", "the next call must try again"
    assert len(rig.provider.calls) == 2


# AC-38-56: an unusable phone number id makes the channel unavailable, no call
@pytest.mark.parametrize("pn", ["", None, "../../../me", "123#frag", "a/b", "a?b"])
def test_ac56_unusable_phone_number_id_is_unavailable_with_no_call(rig, pn):
    bad = rig.channel(pn, token="tok-x", created=0)
    good = rig.channel("pn-good", token="tok-good", created=10)
    rig.msg(bad, wamid="wamid.in-bad", when=1)
    rig.msg(good, wamid="wamid.in-good", when=2)
    got = rig.receipts()
    assert got[bad]["status"] == "channel_unavailable"
    assert got[good]["status"] == "sent"
    assert [c["pn"] for c in rig.provider.calls] == ["pn-good"]  # control: fake counts
    assert rig.unread() == 0


# AC-38-51: any stored metadata shape still gives 200, unread 0 and a call
@pytest.mark.parametrize("meta", [["x"], "plain text", 7])
def test_ac51_odd_metadata_shapes_still_answer_200_and_reset_unread(rig, meta):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1, metadata=meta)
    assert rig.unread() == 1
    r = rig.read()
    assert r.status_code == 200, r.text
    assert r.json()["receipts"][0]["status"] == "sent"
    assert len(rig.provider.calls) == 1
    assert rig.unread() == 0
    again = rig.read()
    assert again.status_code == 200, again.text


# AC-38-63: per call limits and the overall budget
def test_ac63_each_provider_call_carries_connect_3_read_5_write_5(rig):
    ch = rig.channel("pn-A")
    rig.msg(ch, wamid="wamid.in-1", when=1)
    assert rig.receipts()[ch]["status"] == "sent"
    assert len(rig.provider.calls) == 1, "the fake was never reached"
    t = rig.provider.calls[0]["timeout"]
    assert (t.get("connect"), t.get("read"), t.get("write")) == (3.0, 5.0, 5.0)


def test_ac63_a_channel_reached_after_the_budget_answers_failed_with_no_call(
    rig, monkeypatch
):
    import modules.omnichannel.services.public_gateway_service as pgs

    a, b, _ma, _mb = _fresh_unread(rig)
    # control (default budget): the first call is slow, yet both are called
    rig.provider.sleep_on_first = 0.3
    got = rig.receipts()
    assert {x["status"] for x in got.values()} == {"sent"}
    assert len(rig.provider.calls) == 2

    # new customer messages on both channels, tiny budget, slow first call
    rig.msg(a, wamid="wamid.in-A2", when=20)
    rig.msg(b, wamid="wamid.in-B2", when=21)
    rig.provider.calls.clear()
    rig.provider._slept = False
    monkeypatch.setattr(pgs, "READ_RECEIPT_BUDGET_SECONDS", 0.1)
    got = rig.receipts()
    assert len(rig.provider.calls) == 1, "the second channel must not be called"
    called_pn = rig.provider.calls[0]["pn"]
    called, skipped = (a, b) if called_pn == "pn-A" else (b, a)
    assert got[called]["status"] == "sent"
    assert got[skipped]["status"] == "failed"
    assert rig.unread() == 0

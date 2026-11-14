"""Plan 64 S0 - shared Meta plumbing in core (D3, D5, D15; review R1, R2, R4).

- Page subscribe posts the UNION of the app's current fields and the
  requested ones; unsubscribe keeps the rest (DELETE when nothing remains).
- The Meta change-handler registry: one owner per (object, field), dispatched
  before omnichannel's channel lookup / module-active check, failure-isolated.
- The omnichannel import paths are shims onto the SAME core objects.

No real Meta call: httpx MockTransport throughout.
"""
import json
from urllib.parse import parse_qs, urlparse

import fakeredis
import httpx
import pytest

from app.config import settings
from app.integrations.meta import pages as meta_pages
from app.integrations.meta import webhook_registry as reg
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import realtime
from tests.test_omnichannel_channels_messenger import _fb_channel, _messenger_payload, _process

APP_ID = "app-123"
MESSENGER_FIELDS = [
    "messages",
    "messaging_postbacks",
    "message_reads",
    "message_deliveries",
    "message_reactions",
]


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with no handlers and no reservations; whatever the
    boot registered (omnichannel's reservations) is restored afterwards."""
    saved = dict(reg._HANDLERS)
    saved_fields = {k: set(v) for k, v in meta_pages._KNOWN_PAGE_FIELDS.items()}
    reg.reset_meta_change_handlers()
    import modules.omnichannel.adapters.messenger  # noqa: F401 - declares omnichannel's Page fields
    yield
    reg.reset_meta_change_handlers()
    reg._HANDLERS.update(saved)
    meta_pages._KNOWN_PAGE_FIELDS.clear()
    meta_pages._KNOWN_PAGE_FIELDS.update(saved_fields)


@pytest.fixture
def live_meta(monkeypatch):
    """A configured Meta app (no `dev` credential) so the real code path runs."""
    monkeypatch.setattr(settings, "meta_app_id", APP_ID)
    monkeypatch.setattr(settings, "meta_app_secret", "s3cret")


class FakeGraph:
    """Records calls; answers `GET subscribed_apps` with `current`."""

    def __init__(self, current=None, *, get_status=200, other_app_fields=("leadgen_other",)):
        self.current = current
        self.get_status = get_status
        self.other_app_fields = list(other_app_fields)
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/subscribed_apps"):
            if self.get_status != 200:
                return httpx.Response(self.get_status, json={"error": {"message": "nope", "code": 190}})
            data = [{"id": "someone-else", "subscribed_fields": self.other_app_fields}]
            if self.current is not None:
                data.append({"id": APP_ID, "name": "Foundryx", "subscribed_fields": list(self.current)})
            return httpx.Response(200, json={"data": data})
        return httpx.Response(200, json={"success": True})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def posted_fields(self):
        posts = [c for c in self.calls if c.method == "POST"]
        assert len(posts) == 1, [c.method for c in self.calls]
        q = parse_qs(urlparse(str(posts[0].url)).query)
        return q["subscribed_fields"][0].split(",")


# ── Subscribe union (D15 / R1) ──────────────────────────────────────────────


def test_messenger_connect_subscribe_keeps_existing_leadgen(live_meta):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    fake = FakeGraph(current=["messages", "leadgen"])
    MessengerAdapter(client=fake.client()).subscribe_webhook(
        {"access_token": "page-tok"}, "pg-1", "/omnichannel/webhooks/x"
    )
    posted = fake.posted_fields()
    assert "leadgen" in posted and "messages" in posted
    assert set(MESSENGER_FIELDS) <= set(posted)
    assert len(posted) == len(set(posted))  # no duplicates
    get = fake.calls[0]
    assert get.method == "GET" and get.url.path.endswith("/pg-1/subscribed_apps")
    assert get.headers["Authorization"] == "Bearer page-tok"
    # Only THIS app's fields are read - another app's set is never merged in.
    assert "leadgen_other" not in posted


def test_subscribe_when_app_not_yet_subscribed_posts_requested_only(live_meta):
    fake = FakeGraph(current=None)
    out = meta_pages.subscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client())
    assert fake.posted_fields() == ["leadgen"] == out


def test_subscribe_get_failure_falls_back_to_requested_plus_known(live_meta):
    fake = FakeGraph(get_status=500)
    meta_pages.subscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client())
    posted = fake.posted_fields()
    assert "leadgen" in posted
    assert set(MESSENGER_FIELDS) <= set(posted)


def test_subscribe_get_transport_error_never_blocks(live_meta):
    def handler(request):
        if request.method == "GET":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"success": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = meta_pages.subscribe_page_fields("tok", "pg-1", ["leadgen"], client=client)
    assert "leadgen" in out


def test_unsubscribe_leadgen_keeps_messenger_fields(live_meta):
    fake = FakeGraph(current=MESSENGER_FIELDS + ["leadgen"])
    out = meta_pages.unsubscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client())
    assert fake.posted_fields() == MESSENGER_FIELDS == out
    assert not [c for c in fake.calls if c.method == "DELETE"]


def test_unsubscribe_last_field_deletes(live_meta):
    fake = FakeGraph(current=["leadgen"])
    out = meta_pages.unsubscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client())
    assert out == []
    assert [c.method for c in fake.calls] == ["GET", "DELETE"]


def test_unsubscribe_get_failure_changes_nothing(live_meta):
    """A failed read never guesses a remainder: no POST, and above all no
    DELETE of the app's whole subscription."""
    meta_pages.register_page_fields("lead_capture", ["leadgen"])
    fake = FakeGraph(get_status=400)
    assert meta_pages.unsubscribe_page_fields("tok", "pg-1", MESSENGER_FIELDS + ["leadgen"], client=fake.client()) is None
    assert [c.method for c in fake.calls] == ["GET"]


def test_subscribe_update_refused_returns_none(live_meta):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(400, json={"error": {"message": "nope", "code": 100}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert meta_pages.subscribe_page_fields("tok", "pg-1", ["leadgen"], client=client) is None


def test_subscribe_dev_stub_makes_no_call(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "")
    fake = FakeGraph(current=[])
    assert meta_pages.subscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client()) is None
    assert meta_pages.unsubscribe_page_fields("tok", "pg-1", ["leadgen"], client=fake.client()) is None
    assert fake.calls == []


def test_subscribe_dev_credential_makes_no_call(live_meta):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    fake = FakeGraph(current=[])
    MessengerAdapter(client=fake.client()).subscribe_webhook({"dev": True}, "pg-1", "/x")
    assert fake.calls == []


# ── Change-handler registry (D5 / R2) ───────────────────────────────────────


def _leadgen_payload(page_id="pg-leads"):
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1731600000,
                "changes": [
                    {"field": "leadgen", "value": {"leadgen_id": "L1", "page_id": page_id, "form_id": "F1"}}
                ],
            }
        ],
    }


def test_duplicate_registration_raises():
    reg.register_meta_change_handler("page", "leadgen", "lead_capture", lambda *a: None)
    # Same module again is idempotent.
    reg.register_meta_change_handler("page", "leadgen", "lead_capture", lambda *a: None)
    with pytest.raises(reg.DuplicateMetaChangeHandler):
        reg.register_meta_change_handler("page", "leadgen", "other_module", lambda *a: None)
    # A different field or object is a different key.
    reg.register_meta_change_handler("page", "feed", "other_module", lambda *a: None)
    reg.register_meta_change_handler("instagram", "leadgen", "other_module", lambda *a: None)


def test_leadgen_reaches_handler_with_no_messenger_channel(session_factory):
    seen = []
    reg.register_meta_change_handler(
        "page", "leadgen", "lead_capture", lambda db, obj, eid, value: seen.append((obj, eid, value))
    )
    counters = _process(session_factory, "no-such-channel", _leadgen_payload())
    assert seen == [("page", "pg-leads", {"leadgen_id": "L1", "page_id": "pg-leads", "form_id": "F1"})]
    # Omnichannel's own outcome is unchanged: the payload has no channel here.
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


def test_leadgen_reaches_handler_when_omnichannel_inactive(session_factory):
    from app.services.app_store_service import AppStoreService

    _fb_channel(session_factory, external_account_id="pg-leads")
    seen = []
    reg.register_meta_change_handler(
        "page", "leadgen", "lead_capture", lambda db, obj, eid, value: seen.append(eid)
    )
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.commit()
    db.close()
    try:
        counters = _process(session_factory, "x", _leadgen_payload())
        assert seen == ["pg-leads"]
        assert counters == {"messages": 0, "statuses": 0, "skipped": 0}
    finally:
        db2 = session_factory()
        AppStoreService(db2).reactivate(DEFAULT_TENANT_ID, "omnichannel")
        db2.commit()
        db2.close()


def test_raising_handler_does_not_stop_messaging_in_same_payload(session_factory):
    from modules.omnichannel.models import ConversationMessage

    cid = _fb_channel(session_factory, external_account_id="pg-mix")

    def boom(db, obj, eid, value):
        raise RuntimeError("handler exploded")

    reg.register_meta_change_handler("page", "leadgen", "lead_capture", boom)
    payload = _messenger_payload(page_id="pg-mix", mid="m.mix.1", text="still arrives")
    payload["entry"][0]["changes"] = _leadgen_payload("pg-mix")["entry"][0]["changes"]

    counters = _process(session_factory, cid, payload)
    assert counters["messages"] == 1
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.mix.1").one()
        assert row.body == "still arrives"
    finally:
        db.close()


def test_failed_handler_writes_are_rolled_back(session_factory):
    """A handler that adds a row and then raises: the row is NOT committed by
    omnichannel's later commit (savepoint rollback)."""
    from modules.omnichannel.models import Workspace

    cid = _fb_channel(session_factory, external_account_id="pg-rb")

    def half_done(db, obj, eid, value):
        db.add(Workspace(tenant_id=DEFAULT_TENANT_ID, name="should-not-exist-rb"))
        db.flush()
        raise RuntimeError("after a write")

    reg.register_meta_change_handler("page", "leadgen", "lead_capture", half_done)
    payload = _messenger_payload(page_id="pg-rb", mid="m.rb.1")
    payload["entry"][0]["changes"] = _leadgen_payload("pg-rb")["entry"][0]["changes"]
    assert _process(session_factory, cid, payload)["messages"] == 1
    db = session_factory()
    try:
        assert db.query(Workspace).filter(Workspace.name == "should-not-exist-rb").count() == 0
    finally:
        db.close()


def test_successful_handler_writes_are_kept(session_factory):
    from modules.omnichannel.models import Workspace

    cid = _fb_channel(session_factory, external_account_id="pg-ok")

    def enqueue(db, obj, eid, value):
        db.add(Workspace(tenant_id=DEFAULT_TENANT_ID, name="kept-by-handler"))

    reg.register_meta_change_handler("page", "leadgen", "lead_capture", enqueue)
    payload = _messenger_payload(page_id="pg-ok", mid="m.ok.1")
    payload["entry"][0]["changes"] = _leadgen_payload("pg-ok")["entry"][0]["changes"]
    _process(session_factory, cid, payload)
    db = session_factory()
    try:
        assert db.query(Workspace).filter(Workspace.name == "kept-by-handler").count() == 1
    finally:
        db.close()


def test_omnichannel_reserves_its_message_fields():
    from modules.omnichannel import bootstrap

    bootstrap.register_capabilities()
    for obj, field in (("whatsapp_business_account", "messages"), ("page", "messages"),
                       ("instagram", "messages"), ("whatsapp_business_account", "message_template_status_update")):
        with pytest.raises(reg.DuplicateMetaChangeHandler):
            reg.register_meta_change_handler(obj, field, "lead_capture", lambda *a: None)
    # Reservations are not dispatched and leave `leadgen` free.
    assert reg.meta_change_handlers() == []
    reg.register_meta_change_handler("page", "leadgen", "lead_capture", lambda *a: None)
    bootstrap.register_capabilities()  # idempotent re-boot


def test_handler_that_breaks_the_session_is_isolated(session_factory):
    """A handler whose flush fails leaves the session needing a rollback; the
    dispatcher recovers it so omnichannel's processing still commits."""
    from sqlalchemy import text

    cid = _fb_channel(session_factory, external_account_id="pg-flush")

    def bad_sql(db, obj, eid, value):
        db.execute(text("SELECT * FROM no_such_table_here"))

    reg.register_meta_change_handler("page", "leadgen", "lead_capture", bad_sql)
    payload = _messenger_payload(page_id="pg-flush", mid="m.flush.1")
    payload["entry"][0]["changes"] = _leadgen_payload("pg-flush")["entry"][0]["changes"]
    counters = _process(session_factory, cid, payload)
    assert counters["messages"] == 1


def test_unregistered_change_is_ignored_and_payload_path_unchanged(session_factory):
    seen = []
    reg.register_meta_change_handler("page", "leadgen", "lead_capture", lambda *a: seen.append(a))
    payload = _leadgen_payload()
    payload["entry"][0]["changes"][0]["field"] = "feed"
    assert reg.dispatch_meta_changes(None, payload) == 0
    assert seen == []
    # Wrong object, malformed shapes: nothing dispatched, nothing raised.
    other = _leadgen_payload()
    other["object"] = "instagram"
    for bad in (other, None, [], {"object": "page"}, {"object": "page", "entry": "x"},
                {"object": "page", "entry": [None, {"changes": [None, {"field": 3}]}]}):
        assert reg.dispatch_meta_changes(None, bad) == 0


def test_no_handler_registered_dispatch_is_noop():
    assert reg.meta_change_handlers() == []
    assert reg.dispatch_meta_changes(None, _leadgen_payload()) == 0


# ── Shims: omnichannel paths resolve to the SAME core objects (D3) ─────────


def test_omnichannel_shims_point_at_core():
    from app.integrations.meta import errors, graph, signature
    from modules.omnichannel.adapters import base, meta_graph, messenger
    from modules.omnichannel.routers import webhooks

    assert meta_graph.MetaGraphMixin is graph.MetaGraphMixin
    assert meta_graph.provider_error_text is graph.provider_error_text
    assert meta_graph._meta_error_detail is graph._meta_error_detail
    assert meta_graph is graph  # a module alias, so monkeypatches reach the running code
    assert base.SendError is errors.SendError
    assert base.CodeExchangeError is errors.CodeExchangeError
    assert webhooks._signature_valid is signature.signature_valid
    assert issubclass(messenger.MessengerAdapter, meta_pages.MetaPagesMixin)
    for name in ("exchange_code", "exchange_long_lived_token", "list_pages"):
        assert getattr(messenger.MessengerAdapter, name) is getattr(meta_pages.MetaPagesMixin, name)
    assert messenger._DEV_PAGES is meta_pages._DEV_PAGES


def test_graph_base_url_uses_core_version(monkeypatch):
    from app.integrations.meta.graph import graph_base_url
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "meta_graph_version", "v99.0")
    assert graph_base_url() == "https://graph.facebook.com/v99.0"
    assert MessengerAdapter()._base == "https://graph.facebook.com/v99.0"


def test_signature_check_unchanged(monkeypatch):
    import hashlib
    import hmac

    from app.integrations.meta.signature import signature_valid

    body = json.dumps({"object": "page"}).encode()
    monkeypatch.setattr(settings, "meta_app_secret", "topsecret")
    good = "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert signature_valid(body, good)
    assert not signature_valid(body, "sha256=" + "0" * 64)
    assert not signature_valid(body, good[len("sha256="):])
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "environment", "production")
    assert not signature_valid(body, good)
    monkeypatch.setattr(settings, "environment", "development")
    assert signature_valid(body, "")

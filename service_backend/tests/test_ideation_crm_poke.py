"""FEEDBACK-STATUS-POKE (owner ruling 15 Nov ~13:48 for CRM #2433, option c).

When a feedback item's status changes, the shared service writes the status
event the CRM feed reads AND, right after that commit, pokes the tenant's CRM
so it sends the dealer's WhatsApp update at once. Fire and forget: short
timeout, at most one retry, never blocks or breaks the status change; a miss
is fine (the CRM's 15-minute safety check catches it). Config = the tenant's
own ``sorento`` consumer connection (base URL + X-API-Key), never another
tenant's and never the platform's.
"""
import json

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_status_events import (  # noqa: F401
    _auth,
    _create_software_product,
    _events_for,
    _insert_idea,
    _make_contact,
    _setup_with_contact,
    _transition,
    ideation_client,
)

KEY = "poke-test-key-not-real"
BASE = "https://crm.example.test"


@pytest.fixture
def calls(monkeypatch):
    """Capture every outbound poke; run the fire-and-forget sender INLINE so the
    test is deterministic (production runs it on a background thread)."""
    from modules.ideation.services import crm_poke

    seen = []
    state = {"responses": []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if state["responses"]:
            nxt = state["responses"].pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return httpx.Response(nxt)
        return httpx.Response(202)

    monkeypatch.setattr(crm_poke, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(crm_poke, "_spawn", lambda fn: fn())
    seen_state = type("S", (), {})()
    seen_state.requests = seen
    seen_state.queue = state["responses"]
    return seen_state


def _sorento_connection(factory, *, tenant_id=DEFAULT_TENANT_ID, base=BASE, key=KEY, status=None):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    db = factory()
    try:
        conn = Connection(
            tenant_id=tenant_id,
            provider="sorento",
            type="consumer",
            name="Sorento CRM",
            config_json={"baseUrl": base},
            credentials_json=encrypt_secret({"apiKey": key}),
            is_active=True,
        )
        if status:
            conn.status = status
        db.add(conn)
        db.commit()
        return conn.id
    finally:
        db.close()


def test_poke_after_status_change(ideation_client, calls):
    from modules.ideation.services.crm_poke import POKE_PATH

    s = _setup_with_contact(ideation_client)
    _sorento_connection(ideation_client._factory)
    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200, res.text
    assert len(calls.requests) == 1
    req = calls.requests[0]
    assert str(req.url) == f"{BASE}{POKE_PATH}"
    assert req.method == "POST"
    assert req.headers["X-API-Key"] == KEY
    assert "authorization" not in {k.lower() for k in req.headers}
    body = json.loads(req.content)
    event = _events_for(ideation_client._factory, s["idea_id"])[0]
    assert body["event_ids"] == [event.id]
    assert body["latest_seq"] == event.seq


def test_no_connection_no_call_and_status_still_moves(ideation_client, calls):
    s = _setup_with_contact(ideation_client)
    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200
    assert calls.requests == []
    assert len(_events_for(ideation_client._factory, s["idea_id"])) == 1


def test_no_event_no_poke(ideation_client, calls):
    """An operator-authored idea (no requester) writes no event: no poke."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    iid = _insert_idea(ideation_client._factory, pid, problem="operator idea", status_key="captured")
    _sorento_connection(ideation_client._factory)
    assert _transition(ideation_client, h, iid, "triaged").status_code == 200
    assert calls.requests == []


def test_crm_down_status_change_still_ok_one_retry_only(ideation_client, calls):
    s = _setup_with_contact(ideation_client)
    _sorento_connection(ideation_client._factory)
    calls.queue.extend([httpx.ConnectError("down"), httpx.ConnectError("down"), httpx.ConnectError("down")])
    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200
    assert len(calls.requests) == 2  # the call + ONE retry, never a storm
    assert len(_events_for(ideation_client._factory, s["idea_id"])) == 1


def test_5xx_retried_once_4xx_not_retried(ideation_client, calls):
    s = _setup_with_contact(ideation_client)
    _sorento_connection(ideation_client._factory)
    calls.queue.extend([503, 503])
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert len(calls.requests) == 2
    calls.requests.clear()
    calls.queue.extend([401])
    assert _transition(ideation_client, s["h"], s["idea_id"], "linked").status_code == 200
    assert len(calls.requests) == 1


def test_sender_never_raises_and_has_a_short_timeout(ideation_client, monkeypatch):
    """Even a sender bug (here: the connection lookup blowing up) never
    reaches the status change; the HTTP timeout stays short."""
    from modules.ideation.services import crm_poke

    assert crm_poke.POKE_TIMEOUT_SECONDS <= 5
    monkeypatch.setattr(crm_poke, "_spawn", lambda fn: fn())

    def boom(*a, **k):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(crm_poke, "_tenant_target", boom)
    s = _setup_with_contact(ideation_client)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200


def test_never_another_tenants_or_the_platform_connection(ideation_client, calls):
    from app.models import PLATFORM_TENANT_ID
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS
    from app.models.tenant import Tenant

    factory = ideation_client._factory
    db = factory()
    try:
        other = Tenant(name="Other Co", slug="other-poke", status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE])
        db.add(other)
        db.commit()
        other_id = other.id
    finally:
        db.close()
    _sorento_connection(factory, tenant_id=other_id, base="https://other.example.test")
    _sorento_connection(factory, tenant_id=PLATFORM_TENANT_ID, base="https://platform.example.test")
    s = _setup_with_contact(ideation_client)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert calls.requests == []


def test_error_or_inactive_connection_is_skipped(ideation_client, calls):
    from app.models.connection import CONNECTION_STATUS_ERROR

    s = _setup_with_contact(ideation_client)
    _sorento_connection(ideation_client._factory, status=CONNECTION_STATUS_ERROR)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert calls.requests == []


def test_rolled_back_change_never_pokes(ideation_client, calls):
    """The poke rides the COMMIT: an event written then rolled back pokes nothing."""
    from modules.ideation.models import Idea
    from modules.ideation.services import crm_poke

    s = _setup_with_contact(ideation_client)
    _sorento_connection(ideation_client._factory)
    db = ideation_client._factory()
    try:
        db.query(Idea).count()  # a live transaction, as when _write_event queues
        crm_poke.queue_crm_poke(db, DEFAULT_TENANT_ID, "evt-1", 1)
        db.rollback()
        db.query(Idea).count()
        db.commit()
    finally:
        db.close()
    assert calls.requests == []


def test_test_idea_events_never_poke(ideation_client, calls):
    from modules.ideation.models import Idea

    s = _setup_with_contact(ideation_client)
    db = ideation_client._factory()
    try:
        db.query(Idea).filter(Idea.id == s["idea_id"]).first().is_test = True
        db.commit()
    finally:
        db.close()
    _sorento_connection(ideation_client._factory)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert calls.requests == []


def test_fan_out_is_one_poke_per_commit(ideation_client, calls):
    """A survivor's move fans out one event per merged child, all in ONE
    commit: the CRM gets ONE poke listing every event id."""
    s = _setup_with_contact(ideation_client)
    factory = ideation_client._factory
    c2 = _make_contact(factory, phone="+60123459876")
    child = _insert_idea(factory, s["product_id"], problem="child idea", status_key="captured", submitter_contact_id=c2)
    res = ideation_client.post(
        "/ideation/ideas/merge", headers=s["h"], json={"survivorId": s["idea_id"], "ideaIds": [s["idea_id"], child]}
    )
    assert res.status_code in (200, 201), res.text
    _sorento_connection(factory)
    calls.requests.clear()
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert len(calls.requests) == 1
    body = json.loads(calls.requests[0].content)
    assert len(body["event_ids"]) == 2


# ── review round 1 ────────────────────────────────────────────────────────────


def test_rr1_b1_send_waits_past_the_feed_settle_window(monkeypatch):
    """The feed withholds rows younger than SETTLE_WINDOW_SECONDS; a poke sent
    sooner makes the CRM pull nothing. The real spawner delays past it."""
    from modules.ideation.services import crm_poke
    from modules.ideation.services.status_events import SETTLE_WINDOW_SECONDS

    started = []

    class FakeTimer:
        def __init__(self, interval, fn):
            started.append(interval)
            self.daemon = False

        def start(self):
            started.append("started")

    monkeypatch.setattr(crm_poke.threading, "Timer", FakeTimer)
    crm_poke._spawn(lambda: None)
    assert started[0] > SETTLE_WINDOW_SECONDS
    assert started[-1] == "started"


def test_rr1_s1_savepoint_release_never_sends_early(ideation_client, calls):
    """A savepoint inside the transaction must neither send nor drop the
    queued poke: the outer rollback sends nothing ..."""
    from modules.ideation.models import Idea
    from modules.ideation.services import crm_poke

    _sorento_connection(ideation_client._factory)
    db = ideation_client._factory()
    try:
        db.query(Idea).count()
        crm_poke.queue_crm_poke(db, DEFAULT_TENANT_ID, "evt-a", 1)
        with db.begin_nested():
            db.query(Idea).count()
        assert calls.requests == []  # the savepoint release did not send
        db.rollback()
        db.query(Idea).count()
        db.commit()
    finally:
        db.close()
    assert calls.requests == []


def test_rr1_s1_savepoint_rollback_never_drops_earlier_events(ideation_client, calls):
    """... and a savepoint rollback keeps what was queued before it."""
    from modules.ideation.models import Idea
    from modules.ideation.services import crm_poke

    _sorento_connection(ideation_client._factory)
    db = ideation_client._factory()
    try:
        db.query(Idea).count()
        crm_poke.queue_crm_poke(db, DEFAULT_TENANT_ID, "evt-b", 2)
        nested = db.begin_nested()
        db.query(Idea).count()
        nested.rollback()
        crm_poke.queue_crm_poke(db, DEFAULT_TENANT_ID, "evt-c", 3)
        db.commit()
    finally:
        db.close()
    assert len(calls.requests) == 1
    assert json.loads(calls.requests[0].content)["event_ids"] == ["evt-b", "evt-c"]


def test_rr1_s1_fan_out_with_unnumbered_child_is_still_one_poke(ideation_client, calls):
    """Real path: the merged child has no number / link yet, so writing its
    event opens savepoints (numbering + link mint) mid fan-out."""
    from modules.ideation.models import Idea

    s = _setup_with_contact(ideation_client)
    factory = ideation_client._factory
    c2 = _make_contact(factory, phone="+60123459877")
    child = _insert_idea(factory, s["product_id"], problem="unnumbered child", status_key="captured", submitter_contact_id=c2)
    assert ideation_client.post(
        "/ideation/ideas/merge", headers=s["h"], json={"survivorId": s["idea_id"], "ideaIds": [s["idea_id"], child]}
    ).status_code in (200, 201)
    db = factory()
    try:
        row = db.query(Idea).filter(Idea.id == child).first()
        row.idea_number, row.status_token = None, None
        db.commit()
    finally:
        db.close()
    _sorento_connection(factory)
    calls.requests.clear()
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert len(calls.requests) == 1
    assert len(json.loads(calls.requests[0].content)["event_ids"]) == 2


def test_rr1_inactive_connection_is_skipped(ideation_client, calls):
    from app.models.connection import Connection

    s = _setup_with_contact(ideation_client)
    cid = _sorento_connection(ideation_client._factory)
    db = ideation_client._factory()
    try:
        db.query(Connection).filter(Connection.id == cid).first().is_active = False
        db.commit()
    finally:
        db.close()
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert calls.requests == []

"""Plan 56 section A - Meta rate-limit retry on WhatsApp sends (AC-56-01..12).

RED tests written BEFORE the implementation. Black box: the real
``WhatsAppCloudAdapter`` over a mocked httpx transport, ``run_send`` / the Celery
task ``omnichannel_send_message`` and the API-key routes. No private helper of the
unwritten implementation is referenced.

Seams the implementation must honour (assumed by the schedule tests):
* a rate-limited WhatsApp send is re-queued through the Celery task's own
  ``self.retry(...)`` call, with the delay passed as the ``countdown`` keyword
  (seconds). The tests patch ``omnichannel_send_message.retry`` and read
  ``countdown`` from its kwargs.
* ``task.apply(args=[id], retries=n)`` is how the tests set the attempt number.
* on the sync key routes a Meta rate limit surfaces as HTTP 429 with the error
  envelope code ``meta_rate_limited`` and a ``Retry-After`` header (seconds).

Every test seeds its own channel / contact / row. Fake values only.
"""
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.adapters.base import SendError
from modules.omnichannel.adapters.messenger import DEV_RATE_LIMIT_PSID, MessengerAdapter
from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
from modules.omnichannel.models import Channel, ConversationMessage
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_api_gateway import _default_workspace_id
from tests.test_omnichannel_channels_messenger import _fb_channel
from tests.test_omnichannel_channels_send import _fb_contact_with_identity
from tests.test_omnichannel_gateway_channels import _channel, _hdr
from tests.test_omnichannel_mark_read import Rig
from tests.test_omnichannel_one_webhook import _react, _reaction_count, _reaction_rig
from tests.test_omnichannel_outbound_event import _rig, _status_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
RATE_CODES = [130429, 131056, 80007, 4, 17, 32, 613]
CREDS = {"access_token": "tok-fake-56"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd, "_post", lambda *a, **k: _Resp())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── transport helpers ────────────────────────────────────────────────────────
class Meta:
    """A scripted Graph API. ``script`` is a list of (status, json, headers);
    the last entry repeats. Counts every call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        i = min(self.calls, len(self.script) - 1)
        self.calls += 1
        status, body, headers = self.script[i]
        return httpx.Response(status, json=body, headers=headers or {})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def err(status, code, headers=None):
    return (status, {"error": {"message": "throttled", "code": code}}, headers)


OK_SEND = (200, {"messages": [{"id": "wamid.fake-56"}]}, None)


def _wa(meta: Meta) -> WhatsAppCloudAdapter:
    return WhatsAppCloudAdapter(client=meta.client())


def _patch_meta(monkeypatch, meta: Meta):
    """Every Graph adapter built anywhere talks to ``meta`` (fresh client per call)."""
    from modules.omnichannel.adapters import meta_graph

    monkeypatch.setattr(meta_graph.MetaGraphMixin, "_http", lambda self: meta.client())


def _use_real_wa_adapter(monkeypatch, meta: Meta):
    _patch_meta(monkeypatch, meta)
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter",
        lambda channel_type, *a, **k: (
            WhatsAppCloudAdapter(recorder=k.get("recorder")) if channel_type == "WHATSAPP" else MessengerAdapter()
        ),
    )


# ── row / task helpers ───────────────────────────────────────────────────────
def _live_creds(session_factory, channel_id):
    db = session_factory()
    try:
        db.query(Channel).filter(Channel.id == channel_id).one().credentials_json = encrypt_credentials(CREDS)
        db.commit()
    finally:
        db.close()


def _wa_row(client, session_factory, phone, *, events=("message.status",)):
    """A WhatsApp channel with LIVE (non-dev) credentials, a contact with an open
    window and one QUEUED text row. Returns (message_id, channel_id)."""
    r = _rig(client, session_factory, phone, events=events)
    _live_creds(session_factory, r["channel_id"])
    db = session_factory()
    try:
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID,
            contact_id=r["cid"],
            channel_id=r["channel_id"],
            sender_type="AGENT",
            message_type="TEXT",
            body="hi",
            delivery_status="QUEUED",
        )
        db.add(row)
        db.commit()
        return row.id, r["channel_id"]
    finally:
        db.close()


def _row(session_factory, mid):
    db = session_factory()
    try:
        r = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one()
        return r.delivery_status, r.error_code
    finally:
        db.close()


def _set_status(session_factory, mid, status):
    db = session_factory()
    try:
        db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().delivery_status = status
        db.commit()
    finally:
        db.close()


def _run_task(monkeypatch, session_factory, mid, retries=0):
    """Run ``omnichannel_send_message`` once. ``task.retry`` is patched: it records
    its kwargs and raises Celery's Retry, as the real one does. Returns the list
    of recorded retry kwargs."""
    import app.database as appdb
    from celery.exceptions import Retry
    from modules.omnichannel.worker import omnichannel_send_message

    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    recorded = []

    def fake_retry(*args, **kwargs):
        recorded.append(kwargs)
        raise Retry("patched")

    monkeypatch.setattr(omnichannel_send_message, "retry", fake_retry)
    omnichannel_send_message.apply(args=[mid], retries=retries, throw=False)
    return recorded


def _drive_to_the_end(monkeypatch, session_factory, mid):
    """The worker's own full autoretry loop (eager: every retry runs at once)."""
    import app.database as appdb
    from modules.omnichannel.worker import celery_app, omnichannel_send_message

    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    previous = celery_app.conf.get("task_eager_propagates", True)
    celery_app.conf.update(task_eager_propagates=False)
    try:
        omnichannel_send_message.apply(args=[mid], throw=False)
    except Exception:  # noqa: BLE001 - the outcome is what counts
        pass
    finally:
        celery_app.conf.update(task_eager_propagates=previous)


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-01 / 02 - WhatsApp send: 429 and the rate-limit code set are retryable
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_01_send_http_429_is_retryable():
    meta = Meta((429, {"error": {"message": "slow down"}}, None))
    with pytest.raises(SendError) as exc:
        _wa(meta).send(CREDS, "pn-56", "+60100000001", text="hi")
    assert exc.value.transient is True


@pytest.mark.parametrize("code", RATE_CODES)
@pytest.mark.parametrize("status", [400, 403])
def test_ac_56_02_send_rate_limit_codes_are_retryable_whatever_the_http_status(code, status):
    meta = Meta(err(status, code))
    with pytest.raises(SendError) as exc:
        _wa(meta).send(CREDS, "pn-56", "+60100000001", text="hi")
    assert exc.value.transient is True
    assert exc.value.code == str(code)  # Meta's code is kept for the final outcome


def test_ac_56_01_send_run_requeues_row_and_requeues_the_task(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000011")
    meta = Meta(err(429, 130429))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid)
    assert meta.calls == 1
    assert _row(session_factory, mid)[0] == "QUEUED"
    assert len(retries) == 1, "the send task must be re-queued once via task.retry"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-03 - media upload
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_03_upload_http_429_is_retryable():
    meta = Meta((429, {"error": {"message": "slow down"}}, None))
    with pytest.raises(SendError) as exc:
        _wa(meta).upload_media(CREDS, "pn-56", b"data", "image/png")
    assert exc.value.transient is True


@pytest.mark.parametrize("code", RATE_CODES)
def test_ac_56_03_upload_rate_limit_codes_are_retryable(code):
    meta = Meta(err(400, code))
    with pytest.raises(SendError) as exc:
        _wa(meta).upload_media(CREDS, "pn-56", b"data", "image/png")
    assert exc.value.transient is True
    assert exc.value.code == str(code)


def test_ac_56_03_upload_permanent_error_stays_permanent():
    meta = Meta(err(400, 100))
    with pytest.raises(SendError) as exc:
        _wa(meta).upload_media(CREDS, "pn-56", b"data", "image/png")
    assert exc.value.transient is False


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-04 / 09 - permanent codes fail on the first attempt, no retry
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_04_spam_rate_limit_131048_is_not_retryable_at_the_adapter():
    meta = Meta(err(400, 131048))
    with pytest.raises(SendError) as exc:
        _wa(meta).send(CREDS, "pn-56", "+60100000001", text="hi")
    assert exc.value.transient is False
    assert exc.value.code == "131048"


def test_ac_56_04_131048_ends_failed_first_attempt_code_kept_no_retry(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000012")
    meta = Meta(err(400, 131048))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid)
    assert meta.calls == 1
    assert retries == []
    assert _row(session_factory, mid) == ("FAILED", "131048")


@pytest.mark.parametrize("code", [100, 131026])
def test_ac_56_09_permanent_codes_fail_on_the_first_attempt(client, session_factory, monkeypatch, code):
    mid, _ch = _wa_row(client, session_factory, f"+6010000{code % 1000:04d}")
    meta = Meta(err(400, code))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid)
    assert meta.calls == 1
    assert retries == []
    assert _row(session_factory, mid) == ("FAILED", str(code))


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-05 - schedule 15 / 60 / 180 / 600 s + up to 20% jitter, max 4 retries
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("attempt,base", [(0, 15), (1, 60), (2, 180), (3, 600)])
def test_ac_56_05_rate_limited_retry_countdown_follows_the_schedule(client, session_factory, monkeypatch, attempt, base):
    mid, _ch = _wa_row(client, session_factory, f"+601000005{attempt}1")
    meta = Meta(err(429, 130429))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=attempt)
    assert len(retries) == 1, f"attempt {attempt} must re-queue"
    countdown = retries[0].get("countdown")
    assert countdown is not None, "retry must carry an explicit countdown"
    assert base <= countdown <= base * 1.2 + 0.001, (attempt, countdown)
    assert _row(session_factory, mid)[0] == "QUEUED"


def test_ac_56_05_the_fifth_rate_limited_attempt_is_the_last(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000052")
    meta = Meta(err(429, 130429))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=4)
    assert retries == [], "retries are capped at 4: attempt 5 must not re-queue"
    assert _row(session_factory, mid) == ("FAILED", "130429")


@pytest.mark.parametrize("attempt", [0, 1])
def test_ac_56_05_other_transient_errors_keep_todays_schedule(client, session_factory, monkeypatch, attempt):
    mid, _ch = _wa_row(client, session_factory, f"+601000005{attempt}3")
    meta = Meta((503, {"error": {"message": "down", "code": 2}}, None))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=attempt)
    assert len(retries) == 1
    # today: retry_backoff=5 (5 * 2**n with jitter, capped 600): never the 15 s rate-limit floor
    assert retries[0].get("countdown", 0) < 15, retries[0]


def test_ac_56_05_other_transient_errors_keep_todays_count(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000054")
    meta = Meta((503, {"error": {"message": "down", "code": 2}}, None))
    _use_real_wa_adapter(monkeypatch, meta)
    _drive_to_the_end(monkeypatch, session_factory, mid)
    assert meta.calls == 4, "first attempt plus 3 retries, as today"
    assert _row(session_factory, mid)[0] == "FAILED"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-06 - Retry-After raises the next delay, capped at 600
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_06_retry_after_larger_than_schedule_is_used(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000061")
    meta = Meta(err(429, 130429, {"Retry-After": "400"}))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=0)  # scheduled 15 s
    assert len(retries) == 1
    assert 400 <= retries[0]["countdown"] <= 600, retries[0]


def test_ac_56_06_retry_after_is_capped_at_600(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000062")
    meta = Meta(err(429, 130429, {"Retry-After": "9999"}))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=0)
    assert len(retries) == 1
    assert retries[0]["countdown"] == 600, retries[0]


def test_ac_56_06_smaller_retry_after_never_lowers_the_schedule(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000063")
    meta = Meta(err(429, 130429, {"Retry-After": "5"}))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=1)  # scheduled 60 s
    assert len(retries) == 1
    assert 60 <= retries[0]["countdown"] <= 72.001, retries[0]


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-07 - exhausted: FAILED with Meta's code, exactly one FAILED webhook
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_07_no_status_webhook_while_retries_are_pending(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000071")
    meta = Meta(err(429, 130429))
    _use_real_wa_adapter(monkeypatch, meta)
    retries = _run_task(monkeypatch, session_factory, mid, retries=0)
    assert len(retries) == 1  # control: a retry really is pending
    assert _status_rows(session_factory, mid) == []


def test_ac_56_07_budget_exhausted_ends_failed_with_one_failed_webhook(client, session_factory, monkeypatch):
    mid, _ch = _wa_row(client, session_factory, "+60100000072")
    meta = Meta(err(429, 130429))
    _use_real_wa_adapter(monkeypatch, meta)
    _drive_to_the_end(monkeypatch, session_factory, mid)
    assert meta.calls == 5, "first attempt plus 4 rate-limit retries"
    assert _row(session_factory, mid) == ("FAILED", "130429")
    rows = _status_rows(session_factory, mid)
    assert [x["event_id"] for x in rows] == [f"{mid}:FAILED"]
    data = rows[0]["payload"]["data"]
    assert data["deliveryStatus"] == "FAILED" and data["errorCode"] == "130429"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-08 - a retry never sends twice
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_08_rate_limited_then_accepted_sends_once_and_a_later_run_does_not_call_meta(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services.send_runner import run_send

    mid, _ch = _wa_row(client, session_factory, "+60100000081")
    meta = Meta(err(429, 130429), OK_SEND)
    _use_real_wa_adapter(monkeypatch, meta)
    db = session_factory()
    try:
        try:
            run_send(db, mid)
        except Exception:  # noqa: BLE001 - the retry signal is the other tests' business
            pass
        assert _row(session_factory, mid)[0] == "QUEUED"  # control: back in the queue
        assert run_send(db, mid) == "SENT"
        assert meta.calls == 2
        # a second worker picks up the same message after it left QUEUED
        assert run_send(db, mid) == "SENT"
    finally:
        db.close()
    assert meta.calls == 2, "Meta must not be called again for a SENT row"


def test_ac_56_08_row_already_claimed_by_another_worker_is_not_sent(client, session_factory, monkeypatch):
    from modules.omnichannel.services.send_runner import run_send

    mid, _ch = _wa_row(client, session_factory, "+60100000082")
    meta = Meta(OK_SEND)
    _use_real_wa_adapter(monkeypatch, meta)
    _set_status(session_factory, mid, "SENDING")
    db = session_factory()
    try:
        assert run_send(db, mid) == "SENDING"
    finally:
        db.close()
    assert meta.calls == 0
    # control: the same rig does call Meta for a QUEUED row
    _set_status(session_factory, mid, "QUEUED")
    db = session_factory()
    try:
        assert run_send(db, mid) == "SENT"
    finally:
        db.close()
    assert meta.calls == 1


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-10 - Messenger / Instagram unchanged
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("code", [4, 17, 32, 613])
def test_ac_56_10_messenger_still_retries_its_own_rate_limit_codes(code):
    meta = Meta(err(400, code))
    with pytest.raises(SendError) as exc:
        MessengerAdapter(client=meta.client()).send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is True


@pytest.mark.parametrize("code", [130429, 131056, 80007])
def test_ac_56_10_messenger_does_not_adopt_the_whatsapp_only_codes(code):
    meta = Meta(err(400, code))
    with pytest.raises(SendError) as exc:
        MessengerAdapter(client=meta.client()).send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is False


def test_ac_56_10_messenger_rate_limit_keeps_todays_schedule(session_factory, monkeypatch):
    channel_id = _fb_channel(session_factory, external_account_id="pg-56-rl")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid=DEV_RATE_LIMIT_PSID)
    db = session_factory()
    try:
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
            sender_type="AGENT", message_type="TEXT", body="hi", delivery_status="QUEUED",
        )
        db.add(row)
        db.commit()
        mid = row.id
    finally:
        db.close()
    retries = _run_task(monkeypatch, session_factory, mid, retries=0)
    assert len(retries) == 1
    assert retries[0].get("countdown", 0) < 15, retries[0]  # today's backoff, not the WhatsApp schedule
    assert _row(session_factory, mid)[0] == "QUEUED"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-11 - sync key routes answer 429 meta_rate_limited + Retry-After
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def mark_rig(client, session_factory):
    return Rig(client, session_factory, None)


def _read_ready(rig):
    ch = rig.channel("pn-56-read", token="tok-56-read")
    rig.msg(ch, wamid="wamid.in-56-1", when=1)
    return ch


@pytest.mark.parametrize("meta_response", [err(429, 130429), err(400, 130429), err(400, 613)])
def test_ac_56_11_read_receipt_rate_limit_answers_429_meta_rate_limited(mark_rig, monkeypatch, meta_response):
    _read_ready(mark_rig)
    _patch_meta(monkeypatch, Meta(meta_response))
    res = mark_rig.read()
    assert res.status_code == 429, res.text
    assert res.json()["error"]["code"] == "meta_rate_limited", res.text
    retry_after = res.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) >= 1


def test_ac_56_11_read_receipt_passes_a_meta_retry_after_header_through_as_seconds(mark_rig, monkeypatch):
    _read_ready(mark_rig)
    _patch_meta(monkeypatch, Meta(err(429, 130429, {"Retry-After": "30"})))
    res = mark_rig.read()
    assert res.status_code == 429, res.text
    assert int(res.headers["Retry-After"]) >= 30


def test_ac_56_11_read_receipt_other_meta_failure_is_not_a_429(mark_rig, monkeypatch):
    _read_ready(mark_rig)
    meta = Meta(err(400, 100))
    _patch_meta(monkeypatch, meta)
    res = mark_rig.read()
    assert meta.calls == 1  # control: Meta really was asked
    assert res.status_code == 200, res.text  # unchanged: per-channel receipt reports failed
    assert [r["status"] for r in res.json()["receipts"]] == ["failed"]


def test_ac_56_11_read_receipt_control_success_is_200(mark_rig, monkeypatch):
    _read_ready(mark_rig)
    meta = Meta((200, {"success": True}, None))
    _patch_meta(monkeypatch, meta)
    res = mark_rig.read()
    assert meta.calls == 1
    assert res.status_code == 200, res.text


def _reaction_ready(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _channel(session_factory, ws, name="wa-56-react", age_rank=1)
    _live_creds(session_factory, ch)
    _cid, mid = _reaction_rig(session_factory, ws, ch)
    return _hdr(client, ws), mid


@pytest.mark.parametrize("meta_response", [err(429, 130429), err(400, 131056)])
def test_ac_56_11_api_key_reaction_rate_limit_answers_429_meta_rate_limited(
    client, session_factory, monkeypatch, meta_response
):
    hdr, mid = _reaction_ready(client, session_factory)
    _patch_meta(monkeypatch, Meta(meta_response))
    res = _react(client, hdr, mid)
    assert res.status_code == 429, res.text
    assert res.json()["error"]["code"] == "meta_rate_limited", res.text
    retry_after = res.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) >= 1
    assert _reaction_count(session_factory) == 0  # nothing stored for a refused reaction


def test_ac_56_11_api_key_reaction_control_success_is_202(client, session_factory, monkeypatch):
    hdr, mid = _reaction_ready(client, session_factory)
    meta = Meta(OK_SEND)
    _patch_meta(monkeypatch, meta)
    res = _react(client, hdr, mid)
    assert meta.calls == 1
    assert res.status_code == 202, res.text
    assert _reaction_count(session_factory) == 1


def test_ac_56_11_api_key_reaction_other_meta_failure_is_not_a_429(client, session_factory, monkeypatch):
    hdr, mid = _reaction_ready(client, session_factory)
    meta = Meta(err(400, 100))
    _patch_meta(monkeypatch, meta)
    res = _react(client, hdr, mid)
    assert meta.calls == 1
    assert res.status_code != 429, res.text
    assert res.status_code >= 400


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-12 - consumer guide
# ═════════════════════════════════════════════════════════════════════════════
def _guide() -> str:
    return (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()


def test_ac_56_12_guide_lists_codes_schedule_failed_outcome_and_meta_rate_limited():
    guide = _guide()
    for needle in ("130429", "131056", "80007", "meta_rate_limited"):
        assert needle in guide, f"guide must mention {needle}"
    low = guide.lower()
    assert "15" in guide and "60" in guide and "180" in guide and "600" in guide
    i = guide.index("meta_rate_limited")
    window = guide[max(0, i - 2500) : i + 2500].lower()
    assert "retry-after" in window
    assert "131048" in guide  # the one rate-limit code that is NOT retried
    assert "failed" in low and "retr" in low


def test_ac_56_12_guide_keeps_the_per_key_limit_code_distinct():
    guide = _guide()
    assert "`rate_limited`" in guide and "`meta_rate_limited`" in guide


def test_ac_56_12_guide_changelog_has_a_rate_limit_row():
    guide = _guide()
    head = guide.split("## 1. The big picture")[0]
    rows = [ln for ln in head.splitlines() if ln.startswith("> | **2026-")]
    assert any("meta_rate_limited" in ln or "meta rate limit" in ln.lower() for ln in rows), rows

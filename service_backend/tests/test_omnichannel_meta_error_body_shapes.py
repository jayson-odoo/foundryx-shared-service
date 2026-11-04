"""Meta Graph error bodies of any JSON shape fail cleanly.

RED tests written before the fix. Every parser of a Meta error body must treat a
body (or ``error`` value, or text field) of an unexpected JSON type as "no Meta
detail": the caller's normal error path runs, exactly as for a non-JSON body.

Black box over a mocked httpx transport. Fake values only.
"""
import httpx
import pytest

from app.config import settings
from modules.omnichannel.adapters.base import CodeExchangeError, SendError
from modules.omnichannel.adapters.messenger import MessengerAdapter
from modules.omnichannel.adapters.meta_graph import (
    _meta_error_detail,
    is_rate_limited_error,
    is_whatsapp_rate_limited,
    meta_error_code,
)
from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
from tests.test_omnichannel_meta_rate_limit_retry import (
    Meta,
    _patch_meta,
    _reaction_ready,
)
from tests.test_omnichannel_one_webhook import _react, _reaction_count

CREDS = {"access_token": "tok-fake-shape"}

ODD_BODIES = [
    [],
    "x",
    5,
    None,
    {"error": "x"},
    {"error": []},
    {"error": {"code": [1]}},
    {"error": {"message": 5, "error_user_msg": {}, "error_data": "x"}},
]
ODD_IDS = ["list", "str", "int", "null", "err-str", "err-list", "code-list", "text-types"]

# Shapes for the adapter call sites (each used to raise AttributeError/TypeError).
ADAPTER_BODIES = [["x"], {"error": "x"}, {"error": {"message": 5}}, None]
ADAPTER_IDS = ["list", "err-str", "msg-int", "null"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")


def _resp(body, status=400) -> httpx.Response:
    return httpx.Response(status, json=body)


# ── 1. unit: parsers never raise ─────────────────────────────────────────────
@pytest.mark.parametrize("body", ODD_BODIES, ids=ODD_IDS)
def test_rate_limit_checks_never_raise_on_any_body_shape(body):
    assert is_rate_limited_error(_resp(body)) is False
    assert is_whatsapp_rate_limited(_resp(body)) is False


@pytest.mark.parametrize("body", ODD_BODIES, ids=ODD_IDS)
def test_meta_error_code_never_raises_and_is_none_for_odd_shapes(body):
    assert meta_error_code(_resp(body)) is None


@pytest.mark.parametrize("body", ODD_BODIES, ids=ODD_IDS)
def test_meta_error_detail_never_raises_and_falls_back_to_status_text(body):
    assert _meta_error_detail(_resp(body, 400)) == "Meta returned 400."


# ── 2. meta_error_code: short safe codes only ────────────────────────────────
@pytest.mark.parametrize(
    "code,expected",
    [
        ("131056", "131056"),
        (131056, "131056"),
        ("x" * 4000, None),
        ("1" * 4000, None),
        ("12a", None),
        ("١٢٣", None),  # non-ascii digits
        ("1234567890123", None),  # 13 digits
        ("123456789012", "123456789012"),  # 12 digits is the cap
        (True, None),
    ],
)
def test_meta_error_code_accepts_only_short_ascii_digit_codes(code, expected):
    assert meta_error_code(_resp({"error": {"code": code}})) == expected


# ── controls: well-formed Meta errors keep today's text ──────────────────────
def test_control_well_formed_detail_text_unchanged():
    body = {"error": {"message": "Invalid parameter", "error_user_title": "Bad template",
                      "error_user_msg": "Body is too long", "error_data": {"details": "Shorten it"}}}
    assert _meta_error_detail(_resp(body)) == "Bad template - Body is too long - Shorten it"
    assert _meta_error_detail(_resp({"error": {"message": " Oops "}})) == "Oops"


def test_control_well_formed_codes_unchanged():
    assert is_rate_limited_error(_resp({"error": {"code": 613}})) is True
    assert meta_error_code(_resp({"error": {"code": 190}})) == "190"


# ── 3. adapters: same clean failure as a non-JSON error body ─────────────────
def _meta_with(body, status=400):
    return Meta((status, body, None))


def _non_json_client():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, content=b"<html>no</html>")))


def _outcome(fn):
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - the outcome is what is compared
        return (type(exc).__name__, str(exc))
    return ("ok", repr(getattr(result, "__dict__", result)))


def _wa(client):
    return WhatsAppCloudAdapter(client=client)


def _ms(client):
    return MessengerAdapter(client=client)


CALLS = {
    "wa_exchange_code": lambda c: _wa(c).exchange_code("code-1", "https://x.example/cb"),
    "wa_upload_media": lambda c: _wa(c).upload_media(CREDS, "pn-1", b"data", "image/png"),
    "wa_send": lambda c: _wa(c).send(CREDS, "pn-1", "+60100000001", text="hi"),
    "wa_update_business_profile": lambda c: _wa(c).update_business_profile(CREDS, "pn-1", {"about": "a"}),
    "wa_test_connection": lambda c: _wa(c).test_connection(CREDS, "pn-1"),
    "wa_mark_read": lambda c: _wa(c).mark_read(CREDS, "pn-1", "wamid.fake-1"),
    "wa_create_template": lambda c: _wa(c).create_template(CREDS, "waba-1", {"name": "t"}),
    "ms_exchange_code": lambda c: _ms(c).exchange_code("code-1", "https://x.example/cb"),
    "ms_test_connection": lambda c: _ms(c).test_connection(CREDS, "pg-1"),
    "ms_send": lambda c: _ms(c).send(CREDS, "pg-1", "psid-1", text="hi"),
}


@pytest.mark.parametrize("body", ADAPTER_BODIES, ids=ADAPTER_IDS)
@pytest.mark.parametrize("name", sorted(CALLS))
def test_adapter_odd_error_body_fails_like_a_non_json_body(name, body):
    call = CALLS[name]
    baseline = _outcome(lambda: call(_non_json_client()))
    shaped = _outcome(lambda: call(_meta_with(body).client()))
    assert shaped[0] not in ("AttributeError", "TypeError"), shaped
    assert shaped == baseline, (shaped, baseline)


def test_control_adapter_non_json_bodies_fail_cleanly():
    assert _outcome(lambda: CALLS["wa_send"](_non_json_client()))[0] == "SendError"
    assert _outcome(lambda: CALLS["wa_exchange_code"](_non_json_client()))[0] == "CodeExchangeError"
    assert _outcome(lambda: CALLS["wa_test_connection"](_non_json_client()))[0] == "ok"


def test_control_adapter_well_formed_error_text_unchanged():
    body = {"error": {"message": "Bad token", "code": 190}}
    with pytest.raises(SendError) as exc:
        _wa(_meta_with(body).client()).send(CREDS, "pn-1", "+60100000001", text="hi")
    assert "Bad token" in str(exc.value)
    with pytest.raises(CodeExchangeError) as exc2:
        _wa(_meta_with(body).client()).exchange_code("c", "https://x.example/cb")
    assert str(exc2.value) == "Bad token"


# ── 4. route level: reaction with a list-shaped Meta error is a clean refusal ─
@pytest.mark.parametrize("body", [["x"], {"error": "x"}], ids=["list", "err-str"])
def test_api_key_reaction_odd_meta_error_body_is_a_clean_refusal(client, session_factory, monkeypatch, body):
    hdr, mid = _reaction_ready(client, session_factory)
    meta = Meta((400, body, None))
    _patch_meta(monkeypatch, meta)
    res = _react(client, hdr, mid)
    assert meta.calls == 1  # Meta really was asked
    assert 400 <= res.status_code < 500 and res.status_code != 429, res.text
    assert _reaction_count(session_factory) == 0

"""Meta Graph SUCCESS (200) bodies of any JSON shape fail cleanly.

RED tests written before the fix. A 200 body that is not a JSON object, or whose
field has the wrong type, must behave exactly like the same call where the field
is simply missing (same exception type and message, or same return value), never
AttributeError / TypeError / IndexError / KeyError.

Black box over a mocked httpx transport. Fake values only.
"""
import httpx
import pytest

from app.config import settings
from modules.omnichannel.adapters.messenger import MessengerAdapter
from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
from tests.test_omnichannel_meta_error_body_shapes import (
    CREDS,
    _meta_with,
    _outcome,
)

# Whole-body shapes that are not a JSON object.
NON_OBJECT = [[], ["x"], "x", 5, None]
NON_OBJECT_IDS = ["list-empty", "list", "str", "int", "null"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")


def _wa(client):
    return WhatsAppCloudAdapter(client=client)


def _ms(client):
    return MessengerAdapter(client=client)


def _client(body):
    return _meta_with(body, 200).client()


FORBIDDEN = {"AttributeError", "TypeError", "IndexError", "KeyError"}


def _assert_like_missing(call, odd_body, missing_body):
    expected = _outcome(lambda: call(_client(missing_body)))
    got = _outcome(lambda: call(_client(odd_body)))
    assert got[0] not in FORBIDDEN, got
    assert got == expected


# site: (call, missing-field body, extra wrong-type bodies)
SITES = {
    "wa_exchange_code": (
        lambda c: _wa(c).exchange_code("code-1", "https://x.example/cb"),
        {},
        [{"access_token": 5}, {"access_token": ["t"]}],
    ),
    "wa_subscribe_app_checked": (
        lambda c: _wa(c).subscribe_app_checked(CREDS, "waba-1"),
        {},
        [],
    ),
    "wa_check_token": (
        lambda c: _wa(c).check_token(CREDS, "pn-1"),
        {},
        [{"id": 7}, {"id": ["pn-1"]}],
    ),
    "wa_token_details": (
        lambda c: _wa(c).token_details("tok-1"),
        {},
        [{"data": "x"}, {"data": [1]}],
    ),
    "wa_list_waba_numbers": (
        lambda c: _wa(c).list_waba_numbers(CREDS, "waba-1"),
        {},
        [{"data": "x"}, {"data": 5}, {"data": {"id": "1"}}],
    ),
    "wa_upload_media": (
        lambda c: _wa(c).upload_media(CREDS, "pn-1", b"data", "image/png"),
        {},
        [{"id": 7}, {"id": ["m"]}],
    ),
    "wa_get_business_profile": (
        lambda c: _wa(c).get_business_profile(CREDS, "pn-1"),
        {},
        [{"data": "x"}, {"data": 5}, {"data": [5]}, {"data": ["x"]}],
    ),
    "wa_list_templates": (
        lambda c: _wa(c).list_templates(CREDS, "waba-1"),
        {},
        [{"data": "x"}, {"data": 5}, {"data": {"id": "1"}}],
    ),
    "wa_send": (
        lambda c: _wa(c).send(CREDS, "pn-1", "+60100000001", text="hi"),
        {},
        [{"messages": "x"}, {"messages": [5]}, {"messages": ["x"]}, {"messages": [{"id": 7}]}, {"messages": {"id": "w"}}],
    ),
    "wa_fetch_phone_details": (
        lambda c: _wa(c).fetch_phone_details(CREDS, "pn-1"),
        {},
        [],
    ),
    "wa_fetch_waba_details": (
        lambda c: _wa(c).fetch_waba_details(CREDS, "waba-1"),
        {},
        [],
    ),
    "wa_create_template": (
        lambda c: _wa(c).create_template(CREDS, "waba-1", {"name": "t"}),
        {},
        [{"id": 7}, {"id": ["t"]}, {"status": 5}, {"status": ["APPROVED"]}],
    ),
    "wa_upload_resumable": (
        lambda c: _wa(c).upload_resumable(CREDS, "app-1", b"data", "image/png"),
        {},
        [{"id": 7}, {"id": ["s"]}, {"h": 5}, {"h": ["x"]}],
    ),
    "ms_exchange_code": (
        lambda c: _ms(c).exchange_code("code-1", "https://x.example/cb"),
        {},
        [{"access_token": 5}, {"access_token": ["t"]}],
    ),
    "ms_exchange_long_lived_token": (
        lambda c: _ms(c).exchange_long_lived_token(CREDS),
        {},
        [{"access_token": 5}, {"access_token": ["t"]}],
    ),
    "ms_list_pages": (
        lambda c: _ms(c).list_pages(CREDS),
        {},
        [{"data": "x"}, {"data": 5}, {"data": {"id": "1"}}],
    ),
    "ms_upload_media": (
        lambda c: _ms(c).upload_media(CREDS, "pg-1", b"data", "image/png"),
        {},
        [{"attachment_id": 7}, {"attachment_id": ["a"]}],
    ),
    "ms_fetch_profile_name": (
        lambda c: _ms(c).fetch_profile_name(CREDS, "psid-1"),
        {},
        [{"name": 5}, {"name": ["n"]}, {"name": {"first": "x"}}],
    ),
    "ms_send": (
        lambda c: _ms(c).send(CREDS, "pg-1", "psid-1", text="hi"),
        {},
        [{"message_id": 7}, {"message_id": ["m"]}],
    ),
}

CASES = [
    (name, body)
    for name, (_call, _missing, extra) in SITES.items()
    for body in NON_OBJECT + extra
]
CASE_IDS = [f"{name}-{i}" for i, (name, _b) in enumerate(CASES)]


@pytest.mark.parametrize("name,body", CASES, ids=CASE_IDS)
def test_odd_success_body_behaves_like_missing_field(name, body):
    call, missing, _extra = SITES[name]
    _assert_like_missing(call, body, missing)


# resolve_onboarded_assets reads two bodies (debug_token, then phone_numbers).
def _assets_client(debug_body, numbers_body):
    def handler(request: httpx.Request) -> httpx.Response:
        body = debug_body if "debug_token" in request.url.path else numbers_body
        if body is None:
            return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


GOOD_DEBUG = {
    "data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["waba-1"]}]}
}
ODD_DEBUG = NON_OBJECT + [{"data": "x"}, {"data": [1]}, {"data": {"granular_scopes": "x"}},
                          {"data": {"granular_scopes": [5]}},
                          {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": "x"}]}}]
ODD_NUMBERS = NON_OBJECT + [{"data": "x"}, {"data": [5]}, {"data": ["x"]}, {"data": 5}]


@pytest.mark.parametrize("debug_body", ODD_DEBUG, ids=[f"debug-{i}" for i in range(len(ODD_DEBUG))])
def test_resolve_onboarded_assets_odd_debug_token_body_is_no_assets(debug_body):
    expected = {"waba_id": None, "phone_number_id": None, "display_phone_number": None}
    got = _outcome(lambda: _wa(_assets_client(debug_body, {})).resolve_onboarded_assets({"access_token": "tok-1"}))
    assert got[0] not in FORBIDDEN, got
    assert got == ("ok", repr(expected))


@pytest.mark.parametrize("numbers_body", ODD_NUMBERS, ids=[f"numbers-{i}" for i in range(len(ODD_NUMBERS))])
def test_resolve_onboarded_assets_odd_phone_numbers_body_is_no_number(numbers_body):
    expected = {"waba_id": "waba-1", "phone_number_id": None, "display_phone_number": None}
    got = _outcome(lambda: _wa(_assets_client(GOOD_DEBUG, numbers_body)).resolve_onboarded_assets({"access_token": "tok-1"}))
    assert got[0] not in FORBIDDEN, got
    assert got == ("ok", repr(expected))


# ── controls: well-formed bodies behave exactly as today ─────────────────────
def test_control_wa_send_returns_message_id():
    out = _wa(_client({"messages": [{"id": "wamid.fake-1"}]})).send(CREDS, "pn-1", "+60100000001", text="hi")
    assert out == {"external_message_id": "wamid.fake-1"}


def test_control_wa_exchange_code_and_list_templates():
    assert _wa(_client({"access_token": "tok-x"})).exchange_code("c", "https://x.example/cb") == {"access_token": "tok-x"}
    assert _wa(_client({"data": [{"id": "t1"}]})).list_templates(CREDS, "waba-1") == [{"id": "t1"}]


def test_control_wa_upload_check_token_profile():
    assert _wa(_client({"id": "media-9"})).upload_media(CREDS, "pn-1", b"d", "image/png") == "media-9"
    assert _wa(_client({"id": "pn-1"})).check_token(CREDS, "pn-1") == "ok"
    assert _wa(_client({"data": [{"about": "hi"}]})).get_business_profile(CREDS, "pn-1") == {"about": "hi"}


def test_control_messenger_send_pages_upload_name():
    assert _ms(_client({"message_id": "m.fake-1"})).send(CREDS, "pg-1", "psid-1", text="hi") == {"external_message_id": "m.fake-1"}
    assert _ms(_client({"data": [{"id": "pg"}]})).list_pages(CREDS) == [{"id": "pg"}]
    assert _ms(_client({"attachment_id": "att-1"})).upload_media(CREDS, "pg-1", b"d", "image/png") == "att-1"
    assert _ms(_client({"name": "Ada"})).fetch_profile_name(CREDS, "psid-1") == "Ada"
    assert _ms(_client({"access_token": "tok-y"})).exchange_code("c") == {"access_token": "tok-y"}

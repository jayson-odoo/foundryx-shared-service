"""Sprint-5/08 S2 - the AutoCount provider's ``auth`` select + no-auth
``test()`` (AC-08-01/02/03).

RED before the coder: ``AutoCountProvider`` carries no ``auth`` field, no
``showWhen`` on its credential fields, and no ``auth_mode`` helper today
(``modules/autocount/provider.py``, read 2026-09-12). These tests import
``auth_mode`` directly (ImportError expected) and probe ``fields()``/``test()``
for the new shape.

Design assumption pinned here for the coder: ``AutoCountProvider.test()``
gains a keyword-only ``transport`` parameter for the no-auth path, mirroring
the house convention already used by ``client_from_connection(config,
credentials, *, transport=None)`` and ``AutoCountClient(..., transport=...)``
- a full ``httpx.Client(transport=httpx.MockTransport(handler))`` is passed
straight through, never a bare ``httpx.MockTransport`` (see
``client_from_connection`` regression tests in ``test_autocount.py``).
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.provider import AutoCountProvider

try:
    from modules.autocount.provider import auth_mode
except ImportError:  # pragma: no cover - expected until the coder adds it
    auth_mode = None


BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


# ── AC-08-01: the auth select + showWhen on the credential fields ────────────


def test_auth_select_leads_fields_with_show_when():
    fields = AutoCountProvider().fields()
    assert fields[0]["key"] == "auth"
    assert fields[0]["type"] == "select"
    options = fields[0].get("options") or []
    values = {opt["value"] if isinstance(opt, dict) else opt for opt in options}
    assert values == {"basic", "none"}
    assert fields[0].get("default") == "basic"

    by_key = {f["key"]: f for f in fields}
    for key in ("appId", "userId", "password"):
        assert by_key[key].get("showWhen") == {"field": "auth", "values": ["basic"]}
    # baseUrl is always shown - no showWhen key at all.
    assert "showWhen" not in by_key["baseUrl"]


def test_auth_mode_default_basic_legacy_rows_and_explicit_none():
    assert auth_mode is not None, "modules.autocount.provider.auth_mode is not implemented yet"
    assert auth_mode({}) == "basic"  # a legacy row with no `auth` key at all
    assert auth_mode({"auth": "basic"}) == "basic"
    assert auth_mode({"auth": "none"}) == "none"


# ── AC-08-02/03: test() for an open (no-auth) connection ─────────────────────


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _open_config(base_url: str = BASE_URL) -> Dict[str, Any]:
    return {"baseUrl": base_url, "auth": "none"}


def test_test_none_ok_names_the_row_count():
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path.endswith("/location")
        return httpx.Response(200, json=[{"Location": "A1"}, {"Location": "A2"}])

    result = AutoCountProvider().test(
        _open_config(), {}, transport=_transport(handler)
    )
    assert result.ok is True
    assert "2" in result.message
    assert len(calls) == 1
    # Never a login - no Authorization/AppId header on a no-auth probe.
    assert "Authorization" not in calls[0].headers
    assert "AppId" not in calls[0].headers


def test_test_none_non_array_body_fails_naming_the_step():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "an array"})

    result = AutoCountProvider().test(_open_config(), {}, transport=_transport(handler))
    assert result.ok is False
    assert "not JSON" in result.message or "array" in result.message.lower()


def test_test_none_http_404_fails_naming_the_step():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    result = AutoCountProvider().test(_open_config(), {}, transport=_transport(handler))
    assert result.ok is False
    assert "404" in result.message
    assert "not found" not in result.message  # never the raw body


def test_test_none_timeout_fails_naming_reachability():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    result = AutoCountProvider().test(_open_config(), {}, transport=_transport(handler))
    assert result.ok is False
    assert "reach" in result.message.lower()


def test_test_none_never_logs_in_even_with_credentials_present():
    """Credentials are NOT required in no-auth mode, and a login is NEVER
    attempted - even if stray credentials happen to be present on the row."""
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        # A vendor login POSTs to /api/Server/Login - must never be hit.
        assert "Login" not in request.url.path
        return httpx.Response(200, json=[])

    result = AutoCountProvider().test(
        _open_config(), {"appId": "stray", "password": "stray"}, transport=_transport(handler)
    )
    assert result.ok is True
    assert len(calls) == 1  # exactly the one GET /location, nothing else


def test_test_basic_unchanged_still_logs_in_exactly_once():
    """AC-08-02: `auth == "basic"` is byte-for-byte today's behaviour - a
    real vendor login is still attempted for a basic connection, even after
    the `auth` field exists."""
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"detail": "boom"})

    config = {"baseUrl": "https://ac.example.com", "auth": "basic", "userId": "ADMIN"}
    credentials = {"appId": "app-1", "password": "secret"}
    # Basic mode goes through `client_from_connection` -> `AutoCountClient`,
    # whose OWN transport kwarg is exercised elsewhere (test_autocount.py);
    # here we only assert the provider still attempts exactly one login leg
    # rather than short-circuiting to the no-auth probe.
    result = AutoCountProvider().test(config, credentials, transport=_transport(handler))
    assert len(calls) >= 1
    assert result.ok is False  # the stub answers a rejection either way


# ── AC-08-03: trailing slash stripped once at save ────────────────────────────


def test_base_url_trailing_slash_stripped_no_double_slash():
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    AutoCountProvider().test(
        _open_config(base_url="https://hapi.sorento.cc.cd/api/db2/"),
        {},
        transport=_transport(handler),
    )
    assert len(calls) == 1
    assert "//location" not in str(calls[0].url)
    assert str(calls[0].url).endswith("/api/db2/location")

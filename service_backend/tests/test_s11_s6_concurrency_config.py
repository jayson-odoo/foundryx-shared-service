"""Sprint-5/11 S6 - AC-11-01: concurrency is a per-CONNECTION setting,
defaulting to today's behaviour.

RED before the coder, verified at HEAD b4fef31b:
``AutoCountProvider.fields()`` carries exactly ``auth``/``baseUrl``/
``appId``/``userId``/``password``/``pageSize``/``requestTimeoutSeconds`` -
no ``maxConcurrentPages`` field at all, so ``validate_config`` never rejects
it either. ``http_source/client.py::connection_sizing`` returns a bare
``(page_size: int, timeout_seconds: float)`` tuple - callers unpack it
positionally (``self._page_size, timeout_seconds = connection_sizing(...)``
in ``http_source/source.py``, twice more in ``services/etl_service.py``).

ASSUMED NAMES (mirrors the established house style of
``test_s10_s6_connection_sizing.py``'s own "ASSUMED NAMES" section - the
plan names the BEHAVIOUR, not every symbol):

* ``connection_sizing(config)`` returns a ``ConnectionSizing`` object (a
  dataclass or equivalent), never a tuple, carrying ``.page_size``,
  ``.request_timeout_seconds``, ``.max_concurrent_pages`` (int).
* ``AutoCountProvider.fields()`` gains one entry, ``maxConcurrentPages``
  (``type: "number"``, ``default: 1``, ``min: 1``, ``max: 8``), carrying the
  SAME ``showWhen: {"field": "auth", "values": ["none"]}`` mechanism
  ``pageSize``/``requestTimeoutSeconds`` already use.
* ``AutoCountProvider.validate_config`` rejects a non-integer or
  out-of-range ``maxConcurrentPages`` with a 422 naming the field, the same
  opt-in hook ``pageSize``/``requestTimeoutSeconds`` already use.
"""
from __future__ import annotations

from typing import Dict

import pytest

from modules.autocount.provider import AutoCountProvider
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


def _login_headers(client) -> Dict[str, str]:
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


AUTOCOUNT_OPEN_PAYLOAD = {
    "provider": "autocount",
    "name": "Mocha REST concurrency",
    "config": {"auth": "none", "baseUrl": BASE_URL},
    "credentials": {},
}


# ── 1. provider.fields() declares maxConcurrentPages ────────────────────────


def test_provider_fields_declares_max_concurrent_pages_default_1_range_1_8():
    fields = AutoCountProvider().fields()
    by_key = {f["key"]: f for f in fields}

    assert "maxConcurrentPages" in by_key, (
        "AutoCountProvider.fields() has no 'maxConcurrentPages' entry yet (AC-11-01)"
    )
    field = by_key["maxConcurrentPages"]
    assert field["type"] == "number"
    assert field.get("default") == 1, (
        f"maxConcurrentPages must default to 1 (byte-identical to today until an "
        f"operator opts in), got {field.get('default')!r}"
    )
    assert field.get("min") == 1
    assert field.get("max") == 8
    assert field.get("showWhen") == {"field": "auth", "values": ["none"]}, (
        "maxConcurrentPages is meaningless for basic-auth connections (they never "
        "run a page walk against this client) - it must carry the SAME showWhen "
        "mechanism pageSize/requestTimeoutSeconds already use"
    )


# ── 2. save-time validation, naming the field, per AC-11-01's own range ─────


@pytest.mark.parametrize("bad_value", ["abc", "1.5"])
def test_connection_rejects_max_concurrent_pages_non_integer(client, bad_value):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "maxConcurrentPages": bad_value},
    }
    res = client.post("/integrations/connections", json=payload, headers=headers)
    assert res.status_code == 422, res.text
    assert "maxconcurrentpages" in res.json()["detail"].lower()


def test_connection_rejects_max_concurrent_pages_zero(client):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "maxConcurrentPages": "0"},
    }
    res = client.post("/integrations/connections", json=payload, headers=headers)
    assert res.status_code == 422, res.text
    assert "maxconcurrentpages" in res.json()["detail"].lower()


def test_connection_rejects_max_concurrent_pages_over_eight(client):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "maxConcurrentPages": "9"},
    }
    res = client.post("/integrations/connections", json=payload, headers=headers)
    assert res.status_code == 422, res.text
    assert "maxconcurrentpages" in res.json()["detail"].lower()


def test_connection_accepts_max_concurrent_pages_within_range(client):
    """CONTROL, not a RED assertion on its own (mirrors the documented house
    pattern in ``test_s10_s5a_source_reduce_hook.py``): an unrecognised
    config key is accepted/stored silently today, so this already passes
    before the coder touches anything. Kept as a regression trip-wire so a
    coder's range check cannot be so eager it 422s the boundary values
    (1 and 8) themselves - the OTHER tests in this section are this file's
    real RED reason."""
    headers = _login_headers(client)
    for value in ("1", "8"):
        payload = {
            **AUTOCOUNT_OPEN_PAYLOAD,
            "name": f"Mocha REST concurrency {value}",
            "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "maxConcurrentPages": value},
        }
        res = client.post("/integrations/connections", json=payload, headers=headers)
        assert res.status_code == 201, res.text


# ── 3. connection_sizing returns an object, not a tuple, with the new field ─


def test_connection_sizing_returns_object_carrying_max_concurrent_pages():
    from modules.autocount.http_source.client import connection_sizing

    sizing = connection_sizing(
        {"pageSize": "500", "requestTimeoutSeconds": "45", "maxConcurrentPages": "4"}
    )
    for attr in ("page_size", "request_timeout_seconds", "max_concurrent_pages"):
        if not hasattr(sizing, attr):
            pytest.fail(
                f"connection_sizing(...) returned {sizing!r} - AC-11-01 requires a "
                f"ConnectionSizing object (not a bare tuple) carrying .{attr}"
            )
    assert sizing.page_size == 500
    assert sizing.request_timeout_seconds == 45.0
    assert sizing.max_concurrent_pages == 4


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"pageSize": "1000"},
        None,
    ],
)
def test_connection_sizing_no_stored_value_defaults_max_concurrent_pages_to_one(config):
    """A connection saved BEFORE this branch (no maxConcurrentPages key at
    all, or no config at all) must read as concurrency 1 - every existing
    walk is byte-identical to today until an operator opts in."""
    from modules.autocount.http_source.client import connection_sizing

    sizing = connection_sizing(config)
    if not hasattr(sizing, "max_concurrent_pages"):
        pytest.fail(
            f"connection_sizing({config!r}) returned {sizing!r} with no "
            ".max_concurrent_pages attribute at all"
        )
    assert sizing.max_concurrent_pages == 1, (
        f"a connection with no stored maxConcurrentPages must default to 1, got "
        f"{sizing.max_concurrent_pages!r}"
    )


@pytest.mark.parametrize("bad_value", ["0", "9", "abc", "-1", ""])
def test_connection_sizing_never_trusts_an_out_of_range_or_unparsable_value(bad_value):
    """``connection_sizing`` is the ONE reader every call site shares
    (preview, real run, column probe) - it must never hand back a value
    save-time validation would have rejected, the same defensive posture
    ``page_size``/``timeout_seconds`` already take for a legacy/hand-edited
    row."""
    from modules.autocount.http_source.client import connection_sizing

    sizing = connection_sizing({"maxConcurrentPages": bad_value})
    if not hasattr(sizing, "max_concurrent_pages"):
        pytest.fail(
            f"connection_sizing({{'maxConcurrentPages': {bad_value!r}}}) returned "
            f"{sizing!r} with no .max_concurrent_pages attribute at all"
        )
    assert 1 <= sizing.max_concurrent_pages <= 8, (
        f"an out-of-range/unparsable stored maxConcurrentPages ({bad_value!r}) must "
        f"be clamped/defaulted into 1..8, got {sizing.max_concurrent_pages!r}"
    )

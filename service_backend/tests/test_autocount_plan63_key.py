"""Plan 63 (RED): the optional AutoCount API key, AC-63-01..07.

Contract under test (plan 63 section 3.1): ``modules.autocount.write_back.auth.auth_headers``
(``{}`` with no key, or on a read with the reads flag not "yes"; one header otherwise) and
``AuthConfigInvalid`` (code ``AUTH_CONFIG_INVALID``, never the key in the text). The write
client, the write-back reader, the http_source pull client and the provider probe all send
what it returns. Everything runs over MockTransport / the fake vendor: no real host.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import decrypt_secret, encrypt_secret
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.models import AcApiCallLog, AcCompany, AcEntityConfig, AcWriteAction
from modules.autocount.provider import AutoCountProvider
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code, create_body
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3, SECRETS, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

KEY = "k1-SEKRET-7f3a9c"
KEY2 = "k2-ROTATED-51b8e0"
PROBE_URL = "https://autocount-wrapper.example.com/api/db2"
BASELINE_NAMES = {"host", "accept", "accept-encoding", "connection", "user-agent", "content-type", "content-length"}
AUTH_LIKE = {"x-api-key", "authorization", "proxy-authorization", "x-auth-token", "api-key"}


def _auth():
    from modules.autocount.write_back import auth

    return auth


# ------------------------------------------------------------------ helper: auth_headers

def test_ac_63_02_no_key_means_no_header_for_writes_and_reads():
    a = _auth()
    assert a.auth_headers({}, {}, for_read=False) == {}
    assert a.auth_headers({}, {}, for_read=True) == {}
    cfg = {"apiKeyHeader": "X-API-Key", "apiKeyFormat": "Bearer {key}", "apiKeyOnReads": "yes"}
    assert a.auth_headers(cfg, {}, for_read=False) == {}
    assert a.auth_headers(cfg, {"apiKey": ""}, for_read=True) == {}
    assert a.auth_headers(cfg, {"apiKey": "   "}, for_read=True) == {}


def test_ac_63_03_defaults_are_x_api_key_and_plain_key():
    assert _auth().auth_headers({}, {"apiKey": "k1"}, for_read=False) == {"X-API-Key": "k1"}


def test_ac_63_03_custom_header_and_format():
    cfg = {"apiKeyHeader": "Authorization", "apiKeyFormat": "Bearer {key}"}
    assert _auth().auth_headers(cfg, {"apiKey": "k1"}, for_read=False) == {"Authorization": "Bearer k1"}


def test_ac_63_04_reads_flag_gates_only_reads():
    a = _auth()
    creds = {"apiKey": "k1"}
    for flag in (None, "no", "No", ""):
        cfg = {} if flag is None else {"apiKeyOnReads": flag}
        assert a.auth_headers(cfg, creds, for_read=True) == {}, flag
        assert a.auth_headers(cfg, creds, for_read=False) == {"X-API-Key": "k1"}, flag
    yes = {"apiKeyOnReads": "yes"}
    assert a.auth_headers(yes, creds, for_read=True) == {"X-API-Key": "k1"}
    assert a.auth_headers(yes, creds, for_read=False) == {"X-API-Key": "k1"}


BAD_HEADERS = ["Host", "content-length", "Content-Type", "Transfer-Encoding", "Connection", "Cookie",
               "bad name", "bad:name", "x\r\ny", "café", "a(b)"]
BAD_FORMATS = ["no placeholder", "{key}{key}", "Bearer {key} {key}", "Bearer {key}\r\nX-Evil: 1", "{key}\x00"]
BAD_KEYS = ["bad\r\nkey", "bad\nkey", "bad\x01key", "bad\x7fkey"]


@pytest.mark.parametrize("header", BAD_HEADERS)
@pytest.mark.parametrize("for_read", [False, True])
def test_ac_63_06_invalid_header_name_raises_without_the_key(header, for_read):
    a = _auth()
    with pytest.raises(a.AuthConfigInvalid) as ei:
        a.auth_headers({"apiKeyHeader": header, "apiKeyOnReads": "yes"}, {"apiKey": KEY}, for_read=for_read)
    assert ei.value.code == "AUTH_CONFIG_INVALID" and KEY not in str(ei.value)


@pytest.mark.parametrize("fmt", BAD_FORMATS)
def test_ac_63_06_invalid_format_raises_without_the_key(fmt):
    a = _auth()
    with pytest.raises(a.AuthConfigInvalid) as ei:
        a.auth_headers({"apiKeyFormat": fmt}, {"apiKey": KEY}, for_read=False)
    assert ei.value.code == "AUTH_CONFIG_INVALID" and KEY not in str(ei.value)


@pytest.mark.parametrize("bad", BAD_KEYS)
def test_ac_63_06_control_characters_in_the_key_raise(bad):
    a = _auth()
    with pytest.raises(a.AuthConfigInvalid) as ei:
        a.auth_headers({}, {"apiKey": bad}, for_read=False)
    assert ei.value.code == "AUTH_CONFIG_INVALID" and bad not in str(ei.value)


def test_ac_63_06_a_valid_unusual_header_name_is_accepted():
    assert _auth().auth_headers({"apiKeyHeader": "X-Api_Key.1~"}, {"apiKey": "k"}, for_read=False) == {
        "X-Api_Key.1~": "k"}


# ------------------------------------------------------------------ AC-63-01 provider fields + storage

def _field(key: str) -> Dict[str, Any]:
    found = [f for f in AutoCountProvider().fields() if f["key"] == key]
    assert found, f"provider field {key} is missing"
    return found[0]


def test_ac_63_01_the_provider_declares_four_optional_fields_under_auth_none():
    key, header, fmt, reads = (_field(k) for k in ("apiKey", "apiKeyHeader", "apiKeyFormat", "apiKeyOnReads"))
    assert key.get("secret") is True and key["type"] == "password" and not key.get("required")
    assert header.get("default", header.get("defaultValue")) == "X-API-Key"
    assert fmt.get("default", fmt.get("defaultValue")) == "{key}"
    assert reads["type"] == "select" and {o["value"] for o in reads["options"]} == {"no", "yes"}
    assert reads.get("default", reads.get("defaultValue")) == "no"
    for f in (key, header, fmt, reads):
        assert f["showWhen"] == {"field": "auth", "values": ["none"]}
    for f in (header, fmt, reads):
        assert f.get("secret") is not True


def _demo_headers(client) -> Dict[str, str]:
    res = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _payload(**config) -> Dict[str, Any]:
    return {"provider": "autocount", "name": "AC key conn",
            "config": {"auth": "none", "baseUrl": PROBE_URL, **config}, "credentials": {"apiKey": KEY}}


def test_ac_63_01_key_is_encrypted_and_the_rest_is_config_never_in_the_get(client, db):
    hdr = _demo_headers(client)
    res = client.post("/integrations/connections", headers=hdr,
                      json=_payload(apiKeyHeader="Authorization", apiKeyFormat="Bearer {key}", apiKeyOnReads="yes"))
    assert res.status_code == 201, res.text
    created = res.json()
    assert KEY not in res.text
    assert created["config"]["apiKeyHeader"] == "Authorization"
    assert created["config"]["apiKeyFormat"] == "Bearer {key}" and created["config"]["apiKeyOnReads"] == "yes"
    assert "apiKey" not in created["config"]
    row = db.get(Connection, created["id"])
    assert KEY not in json.dumps(row.config_json) and KEY not in (row.credentials_json or "")
    assert decrypt_secret(row.credentials_json)["apiKey"] == KEY
    got = client.get(f"/integrations/connections/{created['id']}", headers=hdr)
    assert got.status_code == 200 and KEY not in got.text


def test_ac_63_01_a_blank_key_on_update_keeps_the_stored_key(client, db):
    hdr = _demo_headers(client)
    created = client.post("/integrations/connections", headers=hdr, json=_payload()).json()
    res = client.patch(f"/integrations/connections/{created['id']}", headers=hdr,
                       json={"config": {"apiKeyHeader": "X-Other"}, "credentials": {"apiKey": ""}})
    assert res.status_code == 200, res.text
    db.expire_all()
    row = db.get(Connection, created["id"])
    assert decrypt_secret(row.credentials_json)["apiKey"] == KEY and row.config_json["apiKeyHeader"] == "X-Other"


def test_ac_63_01_a_legacy_connection_without_the_new_keys_is_no_key():
    assert _auth().auth_headers({"baseUrl": DB3, "userId": "ADMIN", "auth": "none"}, dict(SECRETS),
                                for_read=False) == {}


@pytest.mark.parametrize("cfg", [{"apiKeyHeader": "Host"}, {"apiKeyHeader": "bad name"},
                                 {"apiKeyFormat": "no placeholder"}, {"apiKeyFormat": "{key}{key}"}])
def test_ac_63_06_saving_an_invalid_header_or_format_is_a_422(client, cfg):
    res = client.post("/integrations/connections", headers=_demo_headers(client), json=_payload(**cfg))
    assert res.status_code == 422, res.text
    assert KEY not in res.text


def test_ac_63_06_a_valid_header_and_format_pass_the_save_validator():
    ok = {"auth": "none", "baseUrl": PROBE_URL, "apiKeyHeader": "Authorization", "apiKeyFormat": "Bearer {key}"}
    assert AutoCountProvider().validate_config(ok) is None
    assert AutoCountProvider().validate_config({**ok, "apiKeyHeader": "Cookie"})


# ------------------------------------------------------------------ write path rig

@pytest.fixture
def gw(h, db):
    return Gw(h, db)


def _seen(h):
    """Every request the fake vendor receives (the real transport is wrapped, so the vendor still answers)."""
    seen: List[httpx.Request] = []
    real = h.vendor.transport.handle_request

    def spy(request: httpx.Request):
        seen.append(request)
        return real(request)

    h.monkeypatch.setattr(h.vendor.transport, "handle_request", spy)
    return seen


def _conn(h, *, key=None, header=None, fmt=None, reads=None, config_extra=None) -> None:
    """Rewrite the company's write connection (fresh dicts, committed)."""
    config: Dict[str, Any] = {"baseUrl": DB3, "userId": "ADMIN", "auth": "none"}
    for name, value in (("apiKeyHeader", header), ("apiKeyFormat", fmt), ("apiKeyOnReads", reads)):
        if value is not None:
            config[name] = value
    config.update(config_extra or {})
    creds: Dict[str, Any] = dict(SECRETS)
    if key is not None:
        creds["apiKey"] = key
    h.conn.config_json = config
    h.conn.credentials_json = encrypt_secret(creds)
    h.db.commit()


def _names(request: httpx.Request) -> set:
    return {k.lower() for k in request.headers.keys()}


def _edit(client, gw, doc_key, idem, ref="x"):
    return client.patch(f"{PREFIX}/documents/sales-orders/{doc_key}", headers=gw.hdr(idem),
                        json={"companyCode": "SRT", "header": {"ref": ref}})


def _seed_so(h, key):
    return h.seed_doc("SO", key, [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")])


def _drive_all_verbs(client, gw, base: int, tag: str) -> List[httpx.Request]:
    """create (POST), edit (PUT + GETs), cancel (DELETE) through the real routes."""
    h = gw.h
    seen = _seen(h)
    r = client.post(f"{PREFIX}/documents/quotations", headers=gw.hdr(f"{tag}-create"), json=create_body("QT"))
    assert r.status_code == 200, r.text
    _seed_so(h, base)
    r = _edit(client, gw, base, f"{tag}-edit")
    assert r.status_code == 200, r.text
    _seed_so(h, base + 1)
    r = client.post(f"{PREFIX}/documents/sales-orders/{base + 1}/cancel", headers=gw.hdr(f"{tag}-cancel"),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert {q.method for q in seen} >= {"POST", "PUT", "DELETE", "GET"}, [q.method for q in seen]
    return seen


# ------------------------------------------------------------------ AC-63-02 / 03 writes

def test_ac_63_02_no_key_sends_only_the_headers_main_sends(client, gw):
    _conn(gw.h)
    seen = _drive_all_verbs(client, gw, 6100, "nokey")
    for request in seen:
        assert _names(request) <= BASELINE_NAMES, (request.method, _names(request))
        assert not (_names(request) & AUTH_LIKE)


def test_ac_63_02_a_legacy_connection_without_the_new_keys_sends_no_key(client, gw):
    gw.h.conn.config_json = {"baseUrl": DB3, "userId": "ADMIN"}
    gw.h.db.commit()
    for request in _drive_all_verbs(client, gw, 6150, "legacy"):
        assert not (_names(request) & AUTH_LIKE) and _names(request) <= BASELINE_NAMES


def test_ac_63_03_key_set_adds_exactly_one_header_on_every_write_verb(client, gw):
    h = gw.h
    _conn(h)
    baseline = {(q.method, q.url.path.rsplit("/", 1)[-1].lower()): _names(q)
                for q in _drive_all_verbs(client, gw, 6200, "base")}
    _conn(h, key=KEY)
    seen = _drive_all_verbs(client, gw, 6300, "keyed")
    writes = [q for q in seen if q.method != "GET"]
    assert {q.method for q in writes} == {"POST", "PUT", "DELETE"}
    for request in writes:
        assert request.headers.get("x-api-key") == KEY, request.method
        assert _names(request) - {"x-api-key"} <= BASELINE_NAMES
        leaf = (request.method, request.url.path.rsplit("/", 1)[-1].lower())
        if leaf in baseline:
            assert _names(request) == baseline[leaf] | {"x-api-key"}


def test_ac_63_03_bearer_format_in_authorization(client, gw):
    _conn(gw.h, key="k1", header="Authorization", fmt="Bearer {key}")
    seen = _drive_all_verbs(client, gw, 6400, "bearer")
    for request in (q for q in seen if q.method != "GET"):
        assert request.headers.get("authorization") == "Bearer k1"
        assert "x-api-key" not in _names(request)


# ------------------------------------------------------------------ AC-63-04 reads

@pytest.mark.parametrize("reads,expect", [(None, False), ("no", False), ("yes", True)])
def test_ac_63_04_write_back_reads_carry_the_key_only_when_the_flag_is_yes(client, gw, reads, expect):
    _conn(gw.h, key=KEY, reads=reads)
    seen = _drive_all_verbs(client, gw, 6500, f"reads-{reads}")
    gets = [q for q in seen if q.method == "GET"]
    assert gets
    for request in gets:
        assert (request.headers.get("x-api-key") == KEY) is expect, request.url
    for request in (q for q in seen if q.method != "GET"):
        assert request.headers.get("x-api-key") == KEY


def _probe_calls(config: Dict[str, Any], credentials: Dict[str, Any]) -> List[httpx.Request]:
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"Location": "HQ"}])

    result = AutoCountProvider().test(config, credentials, transport=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok, result.message
    assert calls
    return calls


@pytest.mark.parametrize("reads,expect", [(None, False), ("no", False), ("yes", True)])
def test_ac_63_04_the_probe_carries_the_key_only_when_the_flag_is_yes(reads, expect):
    cfg: Dict[str, Any] = {"auth": "none", "baseUrl": PROBE_URL}
    if reads is not None:
        cfg["apiKeyOnReads"] = reads
    for request in _probe_calls(cfg, {"apiKey": KEY}):
        assert (request.headers.get("x-api-key") == KEY) is expect


def test_ac_63_02_the_probe_without_a_key_is_unchanged():
    for request in _probe_calls({"auth": "none", "baseUrl": PROBE_URL, "apiKeyOnReads": "yes"}, {}):
        assert not (_names(request) & AUTH_LIKE)
        assert request.headers.get("accept") == "application/json"


def test_ac_63_04_the_probe_uses_the_configured_header_and_format():
    cfg = {"auth": "none", "baseUrl": PROBE_URL, "apiKeyOnReads": "yes", "apiKeyHeader": "Authorization",
           "apiKeyFormat": "Bearer {key}"}
    for request in _probe_calls(cfg, {"apiKey": "k1"}):
        assert request.headers.get("authorization") == "Bearer k1"


@pytest.fixture
def pull_rig(session_factory):
    db = session_factory()
    conn = Connection(tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Pull REST",
                      config_json={"baseUrl": PROBE_URL, "auth": "none"}, credentials_json=None, is_active=True)
    db.add(conn)
    db.commit()
    company = AcCompany(tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="MOCHA",
                        company_name="Mocha", name="Mocha", is_active=True)
    db.add(company)
    db.commit()
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT, source_impl="autocount_http",
        source_config={"connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
                       "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
                       "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00"})
    db.add(config)
    db.commit()
    yield db, company, conn, config
    db.close()


def _pull(pull_rig, *, cfg_extra, creds):
    db, company, conn, config = pull_rig
    conn.config_json = {"baseUrl": PROBE_URL, "auth": "none", **cfg_extra}
    conn.credentials_json = encrypt_secret(creds or {})
    db.commit()
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                                         "Data": [{"ItemCode": "SRT-01", "LastModified": "2026-08-01T09:00:00"}]})

    ctx = SourceContext(db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
                        company_service=CompanyService(db))
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT,
                           transport=httpx.Client(transport=httpx.MockTransport(handler)))
    source.fetch_changes(Watermark())
    assert calls
    return calls, source


@pytest.mark.parametrize("reads,expect", [(None, False), ("no", False), ("yes", True)])
def test_ac_63_04_pull_sync_carries_the_key_only_when_the_flag_is_yes(pull_rig, reads, expect):
    extra = {} if reads is None else {"apiKeyOnReads": reads}
    calls, _source = _pull(pull_rig, cfg_extra=extra, creds={"apiKey": KEY})
    for request in calls:
        assert (request.headers.get("x-api-key") == KEY) is expect
        assert request.headers.get("user-agent", "").startswith("Foundryx-AutoCount-ESB/")


def test_ac_63_02_pull_sync_without_a_key_is_unchanged(pull_rig):
    calls, _source = _pull(pull_rig, cfg_extra={"apiKeyOnReads": "yes"}, creds={})
    for request in calls:
        assert not (_names(request) & AUTH_LIKE)
        assert request.headers.get("accept") == "application/json"


def test_ac_63_07_pull_sync_call_records_never_hold_the_key(pull_rig):
    calls, source = _pull(pull_rig, cfg_extra={"apiKeyOnReads": "yes"}, creds={"apiKey": KEY})
    assert calls[0].headers.get("x-api-key") == KEY  # control: the key was really sent
    assert KEY not in repr(source._client.drain_calls())


# ------------------------------------------------------------------ AC-63-05 rotation

def test_ac_63_05_rotation_applies_to_the_very_next_write_and_clearing_removes_it(client, gw):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 6600)
    _conn(h, key=KEY)
    assert _edit(client, gw, 6600, "rot-1", "a").status_code == 200
    assert {q.headers.get("x-api-key") for q in seen if q.method == "PUT"} == {KEY}
    seen.clear()
    _conn(h, key=KEY2)
    assert _edit(client, gw, 6600, "rot-2", "b").status_code == 200
    assert {q.headers.get("x-api-key") for q in seen if q.method == "PUT"} == {KEY2}
    seen.clear()
    _conn(h)  # key cleared
    assert _edit(client, gw, 6600, "rot-3", "c").status_code == 200
    puts = [q for q in seen if q.method == "PUT"]
    assert puts and all(not (_names(q) & AUTH_LIKE) for q in seen)


# ------------------------------------------------------------------ AC-63-06 refusal before send

def _invalid_conn(h, kind: str, value: str) -> None:
    if kind == "header":
        _conn(h, key=KEY, header=value)
    elif kind == "format":
        _conn(h, key=KEY, fmt=value)
    else:
        _conn(h, key=value)


CASES = ([("header", v) for v in BAD_HEADERS] + [("format", v) for v in BAD_FORMATS]
         + [("key", v) for v in BAD_KEYS])


@pytest.mark.parametrize("kind,value", CASES)
def test_ac_63_06_invalid_auth_config_refuses_before_any_request(client, gw, kind, value):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 6700)
    _invalid_conn(h, kind, value)
    r = _edit(client, gw, 6700, "bad-1")
    assert r.status_code != 500, r.text
    assert code(r) == "AUTH_CONFIG_INVALID", r.text
    assert seen == [] and h.vendor.calls == []
    for secret in (KEY, value):
        if len(secret) > 3:
            assert secret not in r.text
    h.db.expire_all()
    action = h.db.query(AcWriteAction).order_by(AcWriteAction.created_at.desc()).first()
    assert action.outcome == "refused" and action.error_code == "AUTH_CONFIG_INVALID"
    factory = h.session_factory()
    try:
        rows = factory.query(AcApiCallLog).all()
    finally:
        factory.close()
    refused = [x for x in rows if x.outcome == "guard_refused" and x.error_code == "AUTH_CONFIG_INVALID"]
    assert refused and len(refused) == len(rows)


def test_ac_63_06_control_a_valid_config_does_send(client, gw):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 6750)
    _conn(h, key=KEY, header="X-Good", fmt="Key {key}")
    assert _edit(client, gw, 6750, "good-1").status_code == 200
    assert any(q.headers.get("x-good") == f"Key {KEY}" for q in seen)


def test_ac_63_06_a_corrupt_stored_credential_is_a_clean_refusal_not_a_500(client, gw):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 6760)
    h.conn.credentials_json = "not-a-fernet-token"
    h.db.commit()
    r = _edit(client, gw, 6760, "corrupt-1")
    assert r.status_code != 500, r.text
    assert code(r) == "AUTH_CONFIG_INVALID" and seen == []


# ------------------------------------------------------------------ AC-63-07 the key is never stored or logged

def _all_text(rows) -> str:
    out = []
    for row in rows:
        for col in row.__table__.columns:
            out.append(str(getattr(row, col.name)))
    return "\n".join(out)


def test_ac_63_07_the_key_is_in_no_row_log_answer_or_connection_get(client, gw, caplog):
    h = gw.h
    caplog.set_level(logging.DEBUG)
    _conn(h, key=KEY, reads=("yes"))
    answers: List[str] = []
    seen = _seen(h)
    # a failing vendor answer too: the stored error body must not echo the key either
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "boom")
    _seed_so(h, 6800)
    answers.append(_edit(client, gw, 6800, "leak-1").text)
    answers.append(_edit(client, gw, 6800, "leak-2", "y").text)
    r = client.post(f"{PREFIX}/documents/quotations", headers=gw.hdr("leak-3"), json=create_body("QT"))
    answers.append(r.text)
    assert any(q.headers.get("x-api-key") == KEY for q in seen), "control: the key was sent"
    factory = h.session_factory()
    try:
        call_rows = factory.query(AcApiCallLog).all()
        action_rows = factory.query(AcWriteAction).all()
    finally:
        factory.close()
    assert call_rows and action_rows
    assert KEY not in _all_text(call_rows)
    assert KEY not in _all_text(action_rows)
    assert KEY not in caplog.text
    for text in answers:
        assert KEY not in text
    got = client.get(f"/integrations/connections/{h.conn.id}", headers=_demo_headers(client))
    assert got.status_code == 200 and KEY not in got.text
    assert KEY not in json.dumps(got.json())

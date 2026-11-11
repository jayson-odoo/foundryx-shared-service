"""Plan 63 review round 1 (RED): AC-63-07 (vendor echo), 08, 09, 16, 17, 20 (format characters),
and the resume refusal row. Rigs and helpers come from the plan 63 key / gate / person files.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.tenant import Tenant
from app.secrets import encrypt_secret
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcApiCallLog, AcEntityConfig, AcWriteAction
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.write_back import auth
from modules.autocount.write_back.service import WriteConnectionError, set_write_connection
from tests.test_autocount_plan63_gate import DB1, _cli, _logs, _point_at, _set, _wc, fresh  # noqa: F401
from tests.test_autocount_plan63_key import (  # noqa: F401
    KEY,
    OTHER_HOST_URL,
    PROBE_URL,
    _all_text,
    _conn,
    _demo_headers,
    _edit,
    _payload,
    _probe_calls,
    _pull,
    _seed_so,
    _seen,
    gw,
    pull_rig,
)
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_operations import OpHarness, World, db, drop_new_row_once, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3, SECRETS, _line
from tests.test_autocount_write_back_runner_qtso import DEBTOR, run_suite
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def _runner():
    from modules.autocount.write_back import runner

    return runner


def _run_db3(h):
    return _runner().run_db3_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                   creditor_code="400-N004", run_tag="R1", **h.factories())


# ------------------------------------------------------------------ AC-63-16 runner writes to a test book only

@pytest.mark.parametrize("env", ["production", "development"])
@pytest.mark.parametrize("suite", ["db3", "qtso"])
def test_ac_63_16_the_runner_suites_refuse_db1_in_every_environment(h, monkeypatch, env, suite):
    _set(monkeypatch, env=env, books="db1,db3")
    _point_at(h, DB1)
    with pytest.raises(Exception) as ei:
        _run_db3(h) if suite == "db3" else run_suite(h)
    assert getattr(ei.value, "code", None) == "WRITE_NOT_ALLOWED", repr(ei.value)
    h.no_http()


@pytest.mark.parametrize("suite", ["db3", "qtso"])
def test_ac_63_16_control_the_runner_suites_do_run_on_db3_in_production(h, monkeypatch, suite):
    _set(monkeypatch, env="production", books="db1,db3")
    result = _run_db3(h) if suite == "db3" else run_suite(h)
    assert result.cases
    assert h.vendor.calls, "the control suite sent no request, so the refusal tests prove nothing"


def _cli_runner(h, monkeypatch, session_factory, tmp_path, suite):
    import app.database as database

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    slug = h.db.get(Tenant, DEFAULT_TENANT_ID).slug
    argv = ["--tenant-slug", slug, "--company-id", h.company.id, "--run-tag", "R1", "--out", str(tmp_path / "r.md"),
            "--suite", suite, "--debtor", DEBTOR]
    if suite == "db3":
        argv += ["--creditor", "400-N004"]
    return _runner().main(argv)


@pytest.mark.parametrize("suite", ["db3", "qtso"])
def test_ac_63_16_the_runner_cli_prints_auth_config_invalid_and_exits_2(h, monkeypatch, capsys, session_factory,
                                                                         tmp_path, suite):
    _conn(h, key=KEY, header="Host")
    rc = _cli_runner(h, monkeypatch, session_factory, tmp_path, suite)
    out = capsys.readouterr()
    assert rc == 2
    assert out.out.strip() == "error: AUTH_CONFIG_INVALID", out.out
    assert "Traceback" not in out.out + out.err and KEY not in out.out + out.err
    h.no_http()


def test_ac_63_16_the_runner_cli_prints_write_not_allowed_for_db1(h, monkeypatch, capsys, session_factory, tmp_path):
    _set(monkeypatch, env="production", books="db1,db3")
    _point_at(h, DB1)
    rc = _cli_runner(h, monkeypatch, session_factory, tmp_path, "db3")
    out = capsys.readouterr().out
    assert rc == 2 and out.strip() == "error: WRITE_NOT_ALLOWED"
    h.no_http()


def test_ac_63_16_control_a_valid_key_config_gets_past_the_refusal(h, monkeypatch, capsys, session_factory, tmp_path):
    runner = _runner()
    monkeypatch.setattr(runner, "AutoCountWriteClient",
                        lambda base_url: __import__("modules.autocount.write_back.client", fromlist=["x"])
                        .AutoCountWriteClient(base_url, transport=h.vendor.transport))
    monkeypatch.setattr(runner, "AutoCountDocReader",
                        lambda base_url: __import__("modules.autocount.write_back.reader", fromlist=["x"])
                        .AutoCountDocReader(base_url, transport=h.vendor.transport))
    _conn(h, key=KEY, header="X-Good")
    rc = _cli_runner(h, monkeypatch, session_factory, tmp_path, "db3")
    out = capsys.readouterr().out
    assert rc in (0, 1) and "error:" not in out
    assert h.vendor.calls


# ------------------------------------------------------------------ AC-63-08 whitespace and field-value hygiene

WS_KEYS = ["ws-key-77 ", " ws-key-77", "ws-key-77 ", "ws-kéy-77"]
WS_FORMATS = ["Bearer {key} ", " {key}", "Bearer {key} ", "{key}é"]


@pytest.mark.parametrize("for_read", [False, True])
@pytest.mark.parametrize("key,fmt", [(k, "{key}") for k in WS_KEYS] + [("ws-key-77", f) for f in WS_FORMATS])
def test_ac_63_08_helper_refuses_whitespace_and_non_field_value_text(key, fmt, for_read):
    with pytest.raises(auth.AuthConfigInvalid) as ei:
        auth.auth_headers({"apiKeyFormat": fmt, "apiKeyOnReads": "yes"}, {"apiKey": key}, for_read=for_read)
    assert ei.value.code == "AUTH_CONFIG_INVALID" and "ws-key-77" not in str(ei.value)


def test_ac_63_08_control_a_clean_key_and_format_pass():
    assert auth.auth_headers({"apiKeyFormat": "Bearer {key}"}, {"apiKey": "ws-key-77"}, for_read=False) == {
        "X-API-Key": "Bearer ws-key-77"}


@pytest.mark.parametrize("key,fmt", [(k, None) for k in WS_KEYS[:2]] + [("ws-key-77", f) for f in WS_FORMATS[:2]])
def test_ac_63_08_a_write_is_refused_before_any_request(client, gw, key, fmt):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 8100)
    _conn(h, key=key, fmt=fmt, reads="yes")
    r = _edit(client, gw, 8100, "ws-1")
    assert r.status_code != 500, r.text
    assert code(r) == "AUTH_CONFIG_INVALID" and "ws-key-77" not in r.text
    assert seen == [] and h.vendor.calls == []


def test_ac_63_08_control_the_same_flow_with_clean_settings_sends(client, gw):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 8101)
    _conn(h, key="ws-key-77", fmt="Bearer {key}", reads="yes")
    assert _edit(client, gw, 8101, "ws-ok").status_code == 200
    assert any(q.headers.get("x-api-key") == "Bearer ws-key-77" for q in seen)


def test_ac_63_08_a_read_with_reads_yes_is_refused_before_any_request(h):
    from modules.autocount.write_back.pull_docs import pull_documents

    World(h)
    _conn(h, key="ws-key-77 ", reads="yes")
    h.vendor.calls.clear()
    result = pull_documents(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                            date_from=date(2026, 11, 4), date_to=date(2026, 11, 4),
                            reader_factory=h.factories()["reader_factory"], sink_factory=h.factories()["sink_factory"])
    assert result.failed and result.error_code == "AUTH_CONFIG_INVALID"
    assert h.vendor.calls == []


@pytest.mark.parametrize("fmt,status", [(" {key}", 422), ("Bearer {key} ", 422), ("Bearer {key}", 201)])
def test_ac_63_08_saving_a_padded_format_is_a_422(client, fmt, status):
    res = client.post("/integrations/connections", headers=_demo_headers(client), json=_payload(apiKeyFormat=fmt))
    assert res.status_code == status, res.text


# ------------------------------------------------------------------ AC-63-07 a vendor answer that echoes the key

ECHO_KEYS = [KEY, "a+b.(c)*[d]-77"]


@pytest.mark.parametrize("key", ECHO_KEYS)
def test_ac_63_07_a_vendor_error_echoing_the_key_is_stored_masked(client, gw, key):
    h = gw.h
    _conn(h, key=key)
    _seed_so(h, 8200)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, f"upstream rejected credential {key} today")
    _edit(client, gw, 8200, "echo-1")
    rows = [x for x in _logs(h) if x.method == "PUT"]
    assert rows and rows[0].outcome == "http_error"
    assert key not in _all_text(rows) and "***" in (rows[0].response_body or "")
    assert "rejected credential ***" in (rows[0].response_body or "")  # the rest of the text is kept
    h.db.expire_all()
    actions = h.db.query(AcWriteAction).all()
    assert actions and key not in _all_text(actions)
    assert "***" in _all_text(actions)


@pytest.mark.parametrize("key", ECHO_KEYS)
def test_ac_63_07_a_vendor_error_echoing_the_key_is_answered_masked(client, gw, key):
    h = gw.h
    _conn(h, key=key)
    _seed_so(h, 8203)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, f"upstream rejected credential {key} today")
    r = _edit(client, gw, 8203, "echo-4")
    assert r.status_code in range(400, 600) and "rejected credential" in r.text  # control: the vendor text is relayed
    assert key not in r.text


def test_ac_63_07_a_failing_read_echoing_the_key_is_stored_masked(client, gw):
    h = gw.h
    _conn(h, key=KEY, reads="yes")
    _seed_so(h, 8201)
    h.vendor.fail_next("GET", "salesorderbydocno", 500, f"bad credential {KEY}")
    _edit(client, gw, 8201, "echo-2")
    gets = [x for x in _logs(h) if x.method == "GET" and x.outcome == "http_error"]
    assert gets and KEY not in _all_text(gets) and "***" in (gets[0].response_body or "")


def test_ac_63_07_control_a_vendor_error_without_the_key_is_stored_as_is(client, gw):
    h = gw.h
    _conn(h, key=KEY)
    _seed_so(h, 8202)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "plain failure text")
    _edit(client, gw, 8202, "echo-3")
    row = next(x for x in _logs(h) if x.method == "PUT")
    assert "plain failure text" in (row.response_body or "") and "***" not in (row.response_body or "")


def test_ac_63_07_a_transport_exception_naming_the_key_never_reaches_the_call_records(pull_rig):
    db, company, conn, config = pull_rig
    conn.config_json = {"baseUrl": PROBE_URL, "auth": "none", "apiKeyOnReads": "yes"}
    conn.credentials_json = encrypt_secret({"apiKey": KEY})
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach upstream with credential {KEY}")

    ctx = SourceContext(db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
                        company_service=CompanyService(db))
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT, transport=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(Exception):
        source.fetch_changes(Watermark())
    records = repr(source._client.drain_calls())
    assert "ConnectError" in records, "control: the failure was recorded"
    assert KEY not in records


# ------------------------------------------------------------------ AC-63-09 reads only to the write host allowlist

def test_ac_63_09_the_probe_sends_no_key_to_a_host_off_the_allowlist():
    cfg = {"auth": "none", "baseUrl": OTHER_HOST_URL, "apiKeyOnReads": "yes"}
    for request in _probe_calls(cfg, {"apiKey": KEY}):
        assert "x-api-key" not in _names_of(request)


def test_ac_63_09_control_the_probe_sends_it_to_an_allowlisted_host():
    cfg = {"auth": "none", "baseUrl": PROBE_URL, "apiKeyOnReads": "yes"}
    assert all(r.headers.get("x-api-key") == KEY for r in _probe_calls(cfg, {"apiKey": KEY}))


def _names_of(request: httpx.Request) -> set:
    return {k.lower() for k in request.headers.keys()}


def test_ac_63_09_pull_sync_sends_no_key_to_a_host_off_the_allowlist(pull_rig):
    calls, source = _pull(pull_rig, cfg_extra={"baseUrl": OTHER_HOST_URL, "apiKeyOnReads": "yes"},
                          creds={"apiKey": KEY})
    assert calls and all("x-api-key" not in _names_of(c) for c in calls)
    assert KEY not in repr(source._client.drain_calls())


def test_ac_63_09_control_pull_sync_sends_it_to_an_allowlisted_host(pull_rig):
    calls, _source = _pull(pull_rig, cfg_extra={"baseUrl": PROBE_URL, "apiKeyOnReads": "yes"}, creds={"apiKey": KEY})
    assert calls and all(c.headers.get("x-api-key") == KEY for c in calls)


def _fake_conn(base_url: str, reads: str, creds: Any) -> SimpleNamespace:
    return SimpleNamespace(config_json={"baseUrl": base_url, "auth": "none", "apiKeyOnReads": reads},
                           credentials_json=creds)


def test_ac_63_09_the_reader_helpers_follow_the_host_allowlist():
    off = _fake_conn(OTHER_HOST_URL, "yes", encrypt_secret({"apiKey": KEY}))
    on = _fake_conn(PROBE_URL, "yes", encrypt_secret({"apiKey": KEY}))
    assert auth.read_headers(off) == {}
    assert auth.connection_headers(off)[1] == {}
    assert auth.read_headers(on) == {"X-API-Key": KEY}
    assert auth.connection_headers(on)[1] == {"X-API-Key": KEY}


@pytest.mark.parametrize("reads", [None, "no"])
def test_ac_63_09_reads_no_never_decrypts_the_credentials(reads):
    conn = _fake_conn(PROBE_URL, reads or "", "garbage-not-a-fernet-token")
    if reads is None:
        conn.config_json.pop("apiKeyOnReads")
    assert auth.read_headers(conn) == {}
    assert auth.connection_headers(conn)[1] == {}


def test_ac_63_09_pull_sync_with_undecryptable_credentials_and_reads_no_runs_as_on_main(pull_rig):
    db, company, conn, config = pull_rig
    conn.config_json = {"baseUrl": PROBE_URL, "auth": "none"}
    conn.credentials_json = "garbage-not-a-fernet-token"
    db.commit()
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                                         "Data": [{"ItemCode": "SRT-01", "LastModified": "2026-08-01T09:00:00"}]})

    ctx = SourceContext(db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
                        company_service=CompanyService(db))
    HttpApiSource(ctx, entity_type=ENTITY_PRODUCT,
                  transport=httpx.Client(transport=httpx.MockTransport(handler))).fetch_changes(Watermark())
    assert calls and all("x-api-key" not in _names_of(c) for c in calls)


def test_ac_63_09_the_write_back_reader_run_with_undecryptable_credentials_and_reads_no_still_reads(h):
    from modules.autocount.write_back.pull_docs import pull_documents

    World(h)
    h.conn.credentials_json = "garbage-not-a-fernet-token"
    h.db.commit()
    result = pull_documents(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                            date_from=date(2026, 11, 4), date_to=date(2026, 11, 4),
                            reader_factory=h.factories()["reader_factory"], sink_factory=h.factories()["sink_factory"])
    assert result.error_code != "AUTH_CONFIG_INVALID"
    assert h.vendor.calls, "the read did not run"


def test_ac_63_09_a_write_with_undecryptable_credentials_is_refused_with_zero_requests(client, gw):
    h = gw.h
    seen = _seen(h)
    _seed_so(h, 8300)
    h.conn.credentials_json = "garbage-not-a-fernet-token"
    h.db.commit()
    r = _edit(client, gw, 8300, "garbage-1")
    assert code(r) == "AUTH_CONFIG_INVALID" and seen == [] and h.vendor.calls == []


# ------------------------------------------------------------------ AC-63-17 URL gate before the live-book check

def _synced(fresh_h, how: str) -> None:
    if how == "rows":
        doc = fresh_h.seed_doc("PO", 8401, [_line("A", 10, 5.0)], stage=False)
        fresh_h.stage("PO", doc, job_id="sql-sync-job")
    else:
        fresh_h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=fresh_h.company.id,
                                      entity_type="customer", source_impl=SOURCE_IMPL_SQL_DB))
        fresh_h.db.commit()


@pytest.mark.parametrize("how", ["rows", "sql"])
def test_ac_63_17_set_write_connection_reports_the_url_gate_first(fresh, monkeypatch, how):
    _set(monkeypatch, env="development", books="db1,db3")
    _synced(fresh, how)
    conn = fresh._connection(DB1, DEFAULT_TENANT_ID)
    with pytest.raises(WriteConnectionError) as ei:
        set_write_connection(fresh.db, tenant_id=DEFAULT_TENANT_ID, company_id=fresh.company.id, connection_id=conn.id)
    assert ei.value.code == "WRITE_NOT_ALLOWED"
    assert _wc(fresh) is None


@pytest.mark.parametrize("how", ["rows", "sql"])
def test_ac_63_17_the_cli_prints_write_not_allowed_for_a_synced_company(fresh, monkeypatch, capsys, session_factory, how):
    _set(monkeypatch, env="development", books="db1,db3")
    _synced(fresh, how)
    code_, out, _conn_row = _cli(fresh, monkeypatch, capsys, session_factory, DB1)
    assert code_ == 2 and out.strip() == "error: WRITE_NOT_ALLOWED"


def test_ac_63_17_control_a_db3_url_on_a_synced_company_is_still_not_test(fresh, monkeypatch):
    _set(monkeypatch, env="development", books="db1,db3")
    _synced(fresh, "rows")
    conn = fresh._connection(DB3, DEFAULT_TENANT_ID)
    with pytest.raises(WriteConnectionError) as ei:
        set_write_connection(fresh.db, tenant_id=DEFAULT_TENANT_ID, company_id=fresh.company.id, connection_id=conn.id)
    assert ei.value.code == "WRITE_COMPANY_NOT_TEST"


def test_ac_63_17_control_production_db1_on_a_synced_company_is_accepted(fresh, monkeypatch):
    _set(monkeypatch, env="production", books="db1,db3")
    _synced(fresh, "rows")
    conn = fresh._connection(DB1, DEFAULT_TENANT_ID)
    set_write_connection(fresh.db, tenant_id=DEFAULT_TENANT_ID, company_id=fresh.company.id, connection_id=conn.id)
    assert _wc(fresh) == conn.id


# ------------------------------------------------------------------ AC-63-20 format characters (Unicode Cf)

def test_ac_63_20_format_characters_are_removed_from_the_name():
    from modules.autocount.write_back import call_log

    assert call_log.person_of(None, "A%E2%80%AEB%E2%80%8BC")[1] == "ABC"      # U+202E, U+200B
    assert call_log.person_of(None, "%EF%BB%BFNam%E2%81%A6e")[1] == "Name"     # U+FEFF, U+2066
    assert call_log.person_of(None, "%E2%80%AE%E2%80%8B") == (None, None)      # nothing left
    assert call_log.person_of(None, "%E9%99%88%E5%A4%A7%E6%96%87")[1] == "陈大文"  # control: letters stay


def test_ac_63_20_format_characters_are_removed_before_the_length_check():
    from modules.autocount.write_back import call_log

    assert call_log.person_of(None, "%41" * 128 + "%E2%80%8B" * 5)[1] == "A" * 128


def test_ac_63_20_a_route_stores_the_name_without_them(client, gw):
    h = gw.h
    h.seed_doc("SO", 8500, [_line("A", 10, 5.0)])
    r = client.patch(f"{PREFIX}/documents/sales-orders/8500",
                     headers=gw.hdr("fmt-1", **{"X-Acting-User-Id": "u-9", "X-Acting-User-Name": "A%E2%80%AEB%E2%80%8BC"}),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    assert {x.acting_user_name for x in _logs(h)} == {"ABC"}
    h.db.expire_all()
    assert h.db.query(AcWriteAction).one().acting_user_name == "ABC"


# ------------------------------------------------------------------ resume refused by the gate

def test_resume_refused_by_the_gate_leaves_one_guard_refused_row(client, db, h, monkeypatch):
    h.delete_on()
    gw = Gw(h, db)
    world = World(h)
    drop_new_row_once(h)
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed", after=1)
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("rs-1"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 502 and r.json()["outcome"] == "needs_attention", r.text  # precondition
    op_id = r.json()["operationId"]
    assert [x for x in _logs(h) if x.outcome == "guard_refused"] == []
    _set(monkeypatch, env="development", books="db1,db3")
    _point_at(h, DB1)
    before = len(h.vendor.calls)
    resumed = client.post(f"{PREFIX}/write-operations/{op_id}/resume", headers=gw.hdr("rs-2"),
                          json={"companyCode": "SRT"})
    assert resumed.status_code != 500, resumed.text
    assert len(h.vendor.calls) == before
    refused = [x for x in _logs(h) if x.outcome == "guard_refused"]
    assert len(refused) == 1 and refused[0].error_code == "WRITE_NOT_ALLOWED"

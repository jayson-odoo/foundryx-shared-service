"""AutoCount ESB — stage 1 (provider, session auth client, erp carve-out).

Every HTTP interaction is mocked. These tests NEVER touch the live demo box.

The behaviours pinned here are the ones verified against the live instance on
2026-07-21 and easy to regress because they are counter-intuitive:
  * ``JWTToken`` is the credential, sent BARE — the ``Token`` GUID is rejected
  * success is ``Status == "Success"``, not the HTTP code, not ``ResultTable``
  * an invalid token surfaces as HTTP 500, not 401
  * a malformed filter is silently ignored and returns the whole table
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.integration_activity import ACTIVITY_SOURCES, SOURCE_AUTOCOUNT
from modules.autocount.client import (
    AutoCountAppError,
    AutoCountAuthError,
    AutoCountClient,
    AutoCountFilterError,
    AutoCountRelayError,
    AutoCountTransportError,
    AutoCountWindowError,
    assert_window,
    build_read_filter,
    validate_read_filter,
)
from modules.autocount.provider import AutoCountProvider

JWT = "eyJhbGciOi.header.signature"
GUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

LOGIN_OK = [
    {
        "Token": GUID,
        "JWTToken": JWT,
        "DatabaseName": "AED_VSOFT",
        "CompanyName": "AED Vsoft Sdn Bhd",
    }
]


def _login_response(payload: Any = None, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=LOGIN_OK if payload is None else payload)


def _relay_500(message: str = "Stream was not readable.") -> httpx.Response:
    """The relay-level failure shape: HTTP 500 + a .NET exception object."""
    return httpx.Response(
        500,
        json={
            "ClassName": "System.InvalidOperationException",
            "Message": message,
            "StackTraceString": "   at AutoCount.Relay.Handler.Read()\n   at ...",
        },
    )


def _app_fail(message: str = "Invalid document type.") -> httpx.Response:
    """The app-level failure shape: HTTP 200, Status Fail, ResultTable PRESENT
    but empty — the reason success must never be inferred from its presence."""
    return httpx.Response(200, json={"Status": "Fail", "Message": message, "ResultTable": []})


def _ok(records: Optional[List[Dict[str, Any]]] = None) -> httpx.Response:
    return httpx.Response(
        200, json={"Status": "Success", "Message": "", "ResultTable": records or []}
    )


class Recorder:
    """A mock transport that replays queued responses and records requests."""

    def __init__(self, responses: List[httpx.Response]):
        self._responses = list(responses)
        self.requests: List[httpx.Request] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"Unexpected extra request to {request.url}")
        return self._responses.pop(0)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handler))

    @property
    def paths(self) -> List[str]:
        return [r.url.path for r in self.requests]


def _client(recorder: Recorder, **kwargs: Any) -> AutoCountClient:
    return AutoCountClient(
        base_url="https://autocount.example.com",
        app_id="app-123",
        user_id="ADMIN",
        password="s3cret",
        transport=recorder.client(),
        **kwargs,
    )


# ── provider registration (AC-13-01) ──────────────────────────────────────


def test_provider_registers_as_an_erp_provider(client):
    """The module's boot hook puts AutoCount in the core provider registry."""
    from app.integrations import all_providers, get_provider

    provider = get_provider("autocount")
    assert provider is not None
    assert provider.type == "erp"
    assert "autocount" in {p.provider for p in all_providers()}


def test_provider_fields_have_no_appsecret_and_no_company(client):
    """Verified live: there is no AppSecret, and the company is DISCOVERED from
    the login response — offering either field would ask for something unusable."""
    keys = [f["key"] for f in AutoCountProvider().fields()]
    assert keys == ["baseUrl", "appId", "userId", "password"]

    fields = {f["key"]: f for f in AutoCountProvider().fields()}
    assert fields["appId"]["secret"] is True
    assert fields["password"]["secret"] is True
    # No company/database selector, and nothing resembling an AppSecret.
    joined = " ".join(keys).lower()
    assert "appsecret" not in joined
    assert "company" not in joined
    assert "database" not in joined


def test_autocount_is_an_activity_source():
    """ACTIVITY_SOURCES is a CLOSED tuple — without this value the ESB's calls
    never render in the Developer Logs console."""
    assert SOURCE_AUTOCOUNT == "autocount"
    assert SOURCE_AUTOCOUNT in ACTIVITY_SOURCES


# ── the JWT-vs-GUID header contract (AC-13-03) ────────────────────────────


def test_login_uses_jwt_token_not_the_guid_and_sends_it_bare():
    """THE trap: the login response carries BOTH a Token GUID and a JWTToken.
    The GUID is rejected everywhere with a misleading HTTP 500. The JWT is sent
    as a BARE Authorization header — no 'Bearer' prefix, not X-API-Key."""
    recorder = Recorder([_login_response(), _ok()])
    with _client(recorder) as ac:
        ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    login_req, read_req = recorder.requests
    assert login_req.url.path == "/api/Server/Login"
    assert login_req.headers["AppId"] == "app-123"

    auth = read_req.headers["Authorization"]
    assert auth == JWT, "the JWT must be sent bare"
    assert not auth.lower().startswith("bearer"), "no Bearer prefix"
    assert GUID not in auth, "the Token GUID must never be used as a credential"
    assert "X-API-Key" not in read_req.headers


def test_login_captures_the_discovered_company():
    """Company is discovered, never configured (D16) — AppId IS the selector."""
    recorder = Recorder([_login_response()])
    with _client(recorder) as ac:
        session = ac.login()

    assert session.database_name == "AED_VSOFT"
    assert session.company_name == "AED Vsoft Sdn Bhd"
    assert session.jwt_token == JWT
    assert session.issued_at.tzinfo is timezone.utc


def test_login_rejects_a_response_carrying_only_the_guid():
    """A response with Token but no JWTToken must fail AT LOGIN — letting it
    through would 500 on every subsequent call with an unrelated-looking error."""
    recorder = Recorder([_login_response([{"Token": GUID, "DatabaseName": "X"}])])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountAuthError, match="JWTToken"):
            ac.login()


def test_login_reads_the_bare_array_response():
    """The response is a bare JSON ARRAY; a dict is an error envelope."""
    recorder = Recorder([_login_response({"Status": "Fail", "Message": "Bad user."})])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountAuthError, match="Bad user."):
            ac.login()


# ── success is Status, never HTTP / ResultTable (AC-13-04) ────────────────


def test_status_fail_on_http_200_is_a_failure():
    """HTTP 200 + Status:'Fail' is the app-level failure shape, and ResultTable
    is PRESENT but empty — so success must be read from Status alone."""
    recorder = Recorder([_login_response(), _app_fail("Invalid document type.")])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountAppError, match="Invalid document type."):
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))


def test_empty_result_table_with_status_success_is_a_valid_empty_read():
    """The mirror of the above: a genuinely empty delta is success, not failure."""
    recorder = Recorder([_login_response(), _ok([])])
    with _client(recorder) as ac:
        # ``read`` returns an ``Unwrapped`` since the per-entity envelope
        # landed: records PLUS what the vendor says is available (AC-14-26).
        assert ac.read("GoodsReceivedNote", build_read_filter(record_count=5)).records == []


def test_relay_500_is_classified_separately_and_hides_the_stack_trace():
    """Relay-level failure is a distinct class, and the .NET StackTraceString
    never reaches the operator-facing message."""
    recorder = Recorder([_login_response(), _relay_500("Object reference not set.")])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError) as excinfo:
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    err = excinfo.value
    assert "Object reference not set." in err.message
    assert "StackTrace" not in err.message
    assert "AutoCount.Relay.Handler" not in err.message
    # The full detail is retained for the log only.
    assert "AutoCount.Relay.Handler" in (err.detail or "")


def test_app_error_and_relay_error_are_distinct_types():
    assert not issubclass(AutoCountAppError, AutoCountRelayError)
    assert not issubclass(AutoCountRelayError, AutoCountAppError)


# ── re-login: proactive on age, reactive exactly once (AC-13-03) ──────────


def test_token_is_proactively_refreshed_once_it_exceeds_max_age():
    """There is no 401 to react to, so age-based renewal is the PRIMARY defence."""
    recorder = Recorder([_login_response(), _ok(), _login_response(), _ok()])
    with _client(recorder, token_max_age_seconds=600) as ac:
        ac.read("GoodsReceivedNote", build_read_filter(record_count=5))
        # Age the held session past its max.
        ac.session.issued_at = datetime.now(timezone.utc) - timedelta(seconds=601)
        ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert recorder.paths == [
        "/api/Server/Login",
        "/api/GoodsReceivedNote/GetGoodsReceivedNote",
        "/api/Server/Login",
        "/api/GoodsReceivedNote/GetGoodsReceivedNote",
    ]


def test_a_fresh_token_is_not_re_logged_in():
    recorder = Recorder([_login_response(), _ok(), _ok()])
    with _client(recorder, token_max_age_seconds=600) as ac:
        ac.read("GoodsReceivedNote", build_read_filter(record_count=5))
        ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert recorder.paths.count("/api/Server/Login") == 1


def test_stream_not_readable_triggers_exactly_one_relogin_and_retry():
    """The ambiguous expiry signal: re-login once, retry once, then succeed."""
    recorder = Recorder([_login_response(), _relay_500(), _login_response(), _ok([{"DocNo": "GRN-1"}])])
    with _client(recorder) as ac:
        records = ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert records.records == [{"DocNo": "GRN-1"}]
    assert recorder.paths == [
        "/api/Server/Login",
        "/api/GoodsReceivedNote/GetGoodsReceivedNote",
        "/api/Server/Login",
        "/api/GoodsReceivedNote/GetGoodsReceivedNote",
    ]


def test_the_retry_happens_at_most_once_then_the_error_propagates():
    """A persistently failing call must NOT loop — one retry, then give up."""
    recorder = Recorder([_login_response(), _relay_500(), _login_response(), _relay_500()])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError):
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert recorder.paths.count("/api/Server/Login") == 2
    assert recorder.paths.count("/api/GoodsReceivedNote/GetGoodsReceivedNote") == 2


def test_the_retry_budget_is_per_call_not_global():
    """A client that already spent a retry on one call must still be able to
    retry the NEXT call — a global counter would silently degrade a long sync."""
    recorder = Recorder(
        [
            _login_response(),
            _relay_500(), _login_response(), _ok([{"DocNo": "A"}]),   # call 1: retried
            _relay_500(), _login_response(), _ok([{"DocNo": "B"}]),   # call 2: retried too
        ]
    )
    with _client(recorder) as ac:
        first = ac.read("GoodsReceivedNote", build_read_filter(record_count=5))
        second = ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert first.records == [{"DocNo": "A"}]
    assert second.records == [{"DocNo": "B"}]


def test_a_non_expiry_relay_error_is_not_retried():
    """Only the ambiguous 'Stream was not readable.' warrants a re-login."""
    recorder = Recorder([_login_response(), _relay_500("Object reference not set.")])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError):
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    assert recorder.paths.count("/api/Server/Login") == 1


# ── filter-shape validation (AC-13-04a) ───────────────────────────────────


def test_a_non_list_identifier_filter_is_rejected_before_sending():
    """Verified live: {"DocNo":"not-an-array"} returns the ENTIRE table with
    Status:'Success'. There is no server error to catch — this is the only
    defence against a full scan masquerading as a delta."""
    with pytest.raises(AutoCountFilterError, match="DocNo"):
        validate_read_filter({"DocNo": "not-an-array", "RecordCount": 5})


def test_bad_record_count_and_date_shapes_are_rejected():
    with pytest.raises(AutoCountFilterError, match="RecordCount"):
        validate_read_filter({"DocNo": [], "RecordCount": 0})
    with pytest.raises(AutoCountFilterError, match="RecordCount"):
        validate_read_filter({"DocNo": [], "RecordCount": "5"})
    with pytest.raises(AutoCountFilterError, match="LastModifiedFrom"):
        validate_read_filter({"DocNo": [], "RecordCount": 5, "LastModifiedFrom": ""})


def test_read_rejects_a_bad_filter_without_making_a_request():
    recorder = Recorder([])  # any request at all would raise
    with _client(recorder) as ac:
        with pytest.raises(AutoCountFilterError):
            ac.read("GoodsReceivedNote", {"DocNo": "GRN-1", "RecordCount": 5})
    assert recorder.requests == []


def test_build_read_filter_produces_a_valid_payload():
    payload = build_read_filter(
        record_count=100,
        last_modified_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
        last_modified_to=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    assert payload == {
        "DocNo": [],
        "RecordCount": 100,
        "LastModifiedFrom": "2026/07/01",
        "LastModifiedTo": "2026/07/21",
    }


def test_window_assertion_fails_when_the_server_ignored_the_filter():
    """A record outside the requested window is the only evidence available
    that the filter was ignored server-side — fail loudly (never advance a
    watermark over data we did not ask for)."""
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)

    assert_window([{"LastModified": "2026/07/15 09:00:00"}], start=start, end=end)

    with pytest.raises(AutoCountWindowError, match="full table scan"):
        assert_window([{"LastModified": "2024/01/02 09:00:00"}], start=start, end=end)


def test_window_assertion_is_day_granular_like_the_vendor_filter():
    """The vendor filter is DATE-only, so a record stamped late on the last day
    of the window is CORRECT data. Comparing against the caller's exact instant
    would reject it — a false alarm on the first real sync."""
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)  # midnight, as a caller writes it

    assert_window([{"LastModified": "2026/07/31 16:37:34"}], start=start, end=end)
    assert_window([{"LastModified": "2026/07/01 00:00:01"}], start=start, end=end)

    # A day outside the window is still caught.
    with pytest.raises(AutoCountWindowError):
        assert_window([{"LastModified": "2026/08/01 00:00:01"}], start=start, end=end)


def test_window_assertion_fails_on_an_unparseable_timestamp():
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)
    with pytest.raises(AutoCountWindowError, match="cannot be verified"):
        assert_window([{"LastModified": None}], start=start, end=end)


def test_read_asserts_the_window_when_one_is_given():
    recorder = Recorder([_login_response(), _ok([{"LastModified": "2020/01/01"}])])
    window = (
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    with _client(recorder) as ac:
        with pytest.raises(AutoCountWindowError):
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5), window=window)


# ── provider.test() actionable messages (AC-13-04) ────────────────────────


def test_test_reports_an_unreachable_host_distinctly():
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = AutoCountProvider()
    transport = httpx.Client(transport=httpx.MockTransport(_boom))
    from modules.autocount import provider as provider_module

    client_obj = provider_module.client_from_connection(
        {"baseUrl": "https://down.example.com", "userId": "ADMIN"},
        {"appId": "app-123", "password": "s3cret"},
        transport=transport,
    )
    with pytest.raises(AutoCountTransportError, match="Could not reach"):
        client_obj.login()

    # And the provider surfaces it without a catch-all.
    result = _test_provider(provider, _boom)
    assert result.ok is False
    assert "Could not reach" in result.message
    assert "Connection failed" not in result.message


def _test_provider(provider: AutoCountProvider, handler, **config: Any):
    """Run provider.test() against a mocked transport by patching the builder."""
    import modules.autocount.provider as provider_module

    original = provider_module.client_from_connection

    def _patched(cfg, creds, *, transport=None):
        return original(
            cfg, creds, transport=httpx.Client(transport=httpx.MockTransport(handler))
        )

    provider_module.client_from_connection = _patched
    try:
        return provider.test(
            {"baseUrl": "https://autocount.example.com", "userId": "ADMIN", **config},
            {"appId": "app-123", "password": "s3cret"},
        )
    finally:
        provider_module.client_from_connection = original


def test_test_reports_a_timeout_distinctly_from_an_auth_rejection():
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    timeout_result = _test_provider(AutoCountProvider(), _timeout)
    assert timeout_result.ok is False
    assert "did not respond within" in timeout_result.message

    auth_result = _test_provider(
        AutoCountProvider(),
        lambda r: httpx.Response(200, json={"Status": "Fail", "Message": "Invalid password."}),
    )
    assert auth_result.ok is False
    assert "rejected the sign-in" in auth_result.message
    assert "User ID" in auth_result.message
    # The two failure messages must not be interchangeable.
    assert timeout_result.message != auth_result.message


def test_test_names_the_appid_on_a_relay_error():
    """A bad AppId surfaces as a relay fault — name the actionable thing."""
    result = _test_provider(AutoCountProvider(), lambda r: _relay_500("Stream was not readable."))
    assert result.ok is False
    assert "AppId" in result.message
    assert "StackTrace" not in result.message


def test_test_succeeds_and_echoes_the_discovered_company():
    result = _test_provider(AutoCountProvider(), lambda r: _login_response())
    assert result.ok is True
    assert "AED Vsoft Sdn Bhd" in result.message
    assert "AED_VSOFT" in result.message


def test_test_rejects_a_missing_or_non_http_base_url():
    provider = AutoCountProvider()
    assert provider.test({}, {}).ok is False
    result = provider.test({"baseUrl": "autocount.example.com"}, {})
    assert result.ok is False
    assert "http://" in result.message


# ── the Sorento consumer provider (plan 14 Task A, AC-14-15) ──────────────


def test_sorento_provider_registers_as_a_consumer_provider(client):
    """The boot hook puts Sorento in the core provider registry, so its outbound
    connection is configured from the same /settings/integrations surface."""
    from app.integrations import all_providers, get_provider

    provider = get_provider("sorento")
    assert provider is not None
    assert provider.type == "consumer"
    assert "sorento" in {p.provider for p in all_providers()}


def test_sorento_provider_fields_are_base_url_and_a_secret_key():
    from modules.autocount.sorento_provider import SorentoProvider

    fields = SorentoProvider().fields()
    keys = [f["key"] for f in fields]
    assert keys == ["baseUrl", "apiKey"]
    by_key = {f["key"]: f for f in fields}
    assert by_key["apiKey"]["secret"] is True
    assert by_key["baseUrl"].get("secret") is not True


def test_sorento_test_rejects_missing_url_and_key():
    from modules.autocount.sorento_provider import SorentoProvider

    provider = SorentoProvider()
    assert provider.test({"baseUrl": ""}, {"apiKey": "k"}).ok is False
    non_http = provider.test({"baseUrl": "sorento.example.com"}, {"apiKey": "k"})
    assert non_http.ok is False and "http://" in non_http.message
    no_key = provider.test({"baseUrl": "http://sorento.test"}, {"apiKey": ""})
    assert no_key.ok is False


def test_sorento_test_names_a_rejected_api_key():
    from modules.autocount.sorento_provider import SorentoProvider

    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "no"}))
    result = SorentoProvider().test(
        {"baseUrl": "http://sorento.test"}, {"apiKey": "bad"}, transport=transport
    )
    assert result.ok is False
    assert "rejected the API key" in result.message


def test_sorento_test_names_an_unreachable_host():
    from modules.autocount.sorento_provider import SorentoProvider

    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    transport = httpx.MockTransport(_boom)
    result = SorentoProvider().test(
        {"baseUrl": "http://sorento.test"}, {"apiKey": "k"}, transport=transport
    )
    assert result.ok is False
    assert "could not reach" in result.message.lower()


def test_sorento_test_uses_x_api_key_and_succeeds_on_a_2xx_probe():
    from modules.autocount.sorento_provider import SorentoProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("X-API-Key")
        seen["authorization"] = "authorization" in {k.lower() for k in request.headers}
        return httpx.Response(200, json={"items": []})

    result = SorentoProvider().test(
        {"baseUrl": "http://sorento.test"}, {"apiKey": "sk_live"},
        transport=httpx.MockTransport(handler),
    )
    assert result.ok is True
    assert seen["x_api_key"] == "sk_live"  # AC-14-15
    assert seen["authorization"] is False  # never Bearer


# ── the erp carve-out (AC-13-02) ──────────────────────────────────────────


def _connection(session, *, type_: str, provider: str, name: str) -> Connection:
    row = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider=provider,
        type=type_,
        name=name,
        config_json={},
        credentials_json="",
    )
    session.add(row)
    session.flush()
    return row


def test_uq_connection_tenant_type_no_longer_blocks_multiple_erp_rows(session_factory):
    """D17: 'erp' is carved out of the one-active-per-type index, so the TYPE
    index no longer blocks a tenant's second AutoCount company.

    (Distinct provider keys here isolate the assertion to the TYPE index — the
    sibling (tenant, provider) index is a SEPARATE, still-open blocker, pinned
    by the xfail below.)"""
    db = session_factory()
    try:
        _connection(db, type_="erp", provider="autocount", name="AED_VSOFT")
        _connection(db, type_="erp", provider="some-other-erp", name="AED_OTHER")
        db.commit()

        rows = (
            db.query(Connection)
            .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.type == "erp")
            .all()
        )
        assert len(rows) == 2
    finally:
        db.close()


def test_a_tenant_may_hold_several_active_autocount_connections(session_factory):
    """AC-13-02: a tenant onboards a second AutoCount COMPANY. Both rows are
    provider='autocount' — that is the real-world shape, since AppId (not the
    provider key) is the company selector."""
    db = session_factory()
    try:
        _connection(db, type_="erp", provider="autocount", name="AED_VSOFT")
        _connection(db, type_="erp", provider="autocount", name="AED_OTHER")
        db.commit()
        assert (
            db.query(Connection)
            .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.type == "erp")
            .count()
            == 2
        )
    finally:
        db.close()


def test_storage_still_allows_only_one_active_connection_per_type(session_factory):
    """REGRESSION GUARD: the erp carve-out must not relax storage/email, whose
    resolution (``resolve_for_type``) requires a single deterministic target."""
    db = session_factory()
    try:
        _connection(db, type_="storage", provider="s3", name="Primary bucket")
        db.commit()
        with pytest.raises(IntegrityError):
            _connection(db, type_="storage", provider="r2", name="Second bucket")
    finally:
        db.rollback()
        db.close()


def test_email_still_allows_only_one_active_connection_per_type(session_factory):
    db = session_factory()
    try:
        _connection(db, type_="email", provider="smtp", name="Primary SMTP")
        db.commit()
        with pytest.raises(IntegrityError):
            _connection(db, type_="email", provider="smtp-alt", name="Backup SMTP")
    finally:
        db.rollback()
        db.close()


# ── module hygiene (AC-13-45) ─────────────────────────────────────────────


def test_module_implements_the_full_bootstrap_contract():
    from modules.autocount import bootstrap

    for hook in (
        "install",
        "install_tenant",
        "update_tenant",
        "uninstall_tenant",
        "register_capabilities",
        "register_engine_entities",
    ):
        assert callable(getattr(bootstrap, hook)), f"missing bootstrap hook: {hook}"


def test_module_tables_live_in_their_own_schema():
    from modules.autocount.db import AUTOCOUNT_SCHEMA, AutocountBase

    assert AUTOCOUNT_SCHEMA == "app_autocount"
    assert AutocountBase.metadata.schema == AUTOCOUNT_SCHEMA
    # Module tables must never leak into core's metadata.
    from app.database import Base

    assert not (set(AutocountBase.metadata.tables) & set(Base.metadata.tables))


def test_module_permission_keys_are_namespaced_and_installed(client):
    """A duplicate GLOBAL permission key throws a UNIQUE violation at bootstrap
    (``sync_permissions`` is delete-by-module) — every key must be autocount.*"""
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200
    granted = response.json()["user"]["permissions"]
    assert "autocount.companies.read" in granted
    assert "autocount.sync.run" in granted
    assert all(key.startswith("autocount.") for key in granted if "autocount" in key)


# ── relay detail is MASKED (code review, sprint-4/13) ─────────────────────
#
# ``detail`` is explicitly intended to be LOGGED (the class docstring says so),
# and a .NET relay fault echoes the REQUEST — whose body on
# ``POST /api/Server/Login`` is ``{"UserID", "Password"}`` under an ``AppId``
# header. Before this fix ``_raise_relay``/``_json`` were the only ``detail=``
# sites in client.py that did NOT go through ``_safe``.


def test_the_relay_raw_text_detail_branch_is_masked_and_capped():
    """The exact line the review flagged: when the 500's body is NOT a dict,
    ``_raise_relay`` falls back to interpolating ``response.text`` raw. That
    branch now goes through ``_safe`` like every other ``detail=`` in the file.

    Note the honest limit, stated in the method docstring: ``_safe`` on free
    TEXT masks PAN-shaped runs and caps length — it cannot key-redact a
    ``Password=`` embedded in prose. The structural pass (below) is the
    defence that actually scales; this is the floor.
    """
    recorder = Recorder(
        [
            _login_response(),
            # A JSON *list* body — parses, but is not a dict, so the composer is
            # skipped and the raw-text detail stands.
            httpx.Response(500, json=["relay down, card 4111111111111111 " + "y" * 5000]),
        ]
    )
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError) as excinfo:
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    detail = excinfo.value.detail or ""
    assert "4111111111111111" not in detail
    assert "***1111" in detail
    assert len(detail) <= 2000


def test_a_relay_detail_masks_an_echoed_credential_structurally():
    """The dict branch composes out of a ``mask_payload``-ed COPY of the .NET
    object, so a credential key nested anywhere in it is redacted before it can
    reach a string — including the operator-facing ``message``/``raw_message``.
    """
    relay = httpx.Response(
        500,
        json={
            "ClassName": "System.InvalidOperationException",
            # The .NET message itself carrying the echoed request object.
            "Message": "Login failed.",
            "StackTraceString": "   at AutoCount.Relay.Handler.Read()",
            "Request": {
                "AppId": "app-123",
                "UserID": "ADMIN",
                "Password": "s3cret",
                "Token": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            },
        },
    )
    recorder = Recorder([_login_response(), relay])
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError) as excinfo:
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    err = excinfo.value
    blob = f"{err.message} {err.detail} {err.raw_message}"
    for credential in ("s3cret", "app-123", "3f2504e0"):
        assert credential not in blob
    # Masking must not blank the diagnostics it exists to protect.
    assert "Login failed." in (err.detail or "")
    assert "AutoCount.Relay.Handler" in (err.detail or "")


def test_a_non_json_relay_body_detail_is_masked_and_capped():
    """The ``_json`` branch: the body did not parse, so there is no object graph
    to mask structurally — it must at minimum go through ``_safe`` (PAN masking
    + the 2000-char cap) rather than being interpolated raw."""
    recorder = Recorder(
        [
            _login_response(),
            # 200 + non-JSON: taken by ``_json``, not ``_raise_relay``.
            httpx.Response(
                200,
                text="<html>gateway error card 4111111111111111 " + "x" * 5000,
                headers={"content-type": "text/html"},
            ),
        ]
    )
    with _client(recorder) as ac:
        with pytest.raises(AutoCountRelayError) as excinfo:
            ac.read("GoodsReceivedNote", build_read_filter(record_count=5))

    detail = excinfo.value.detail or ""
    assert "4111111111111111" not in detail
    assert "***1111" in detail
    assert len(detail) <= 2000


# ── AppId is a credential to the masker (code review, sprint-4/13) ────────


def test_the_masker_treats_appid_as_a_credential():
    """AC-13-42 rested on "no call site logs AppId today", which is a defence
    that does not survive the next slice. The masker must redact it by KEY."""
    from app.integrations.masking import mask_payload

    masked = mask_payload(
        {
            "AppId": "app-123",
            "appId": "app-123",
            "app_id": "app-123",
            "nested": [{"APPID": "app-123"}],
            # Not a credential — must survive, or the log becomes useless.
            "DatabaseName": "AED_VSOFT",
        }
    )
    assert masked["AppId"] == "***"
    assert masked["appId"] == "***"
    assert masked["app_id"] == "***"
    assert masked["nested"][0]["APPID"] == "***"
    assert masked["DatabaseName"] == "AED_VSOFT"

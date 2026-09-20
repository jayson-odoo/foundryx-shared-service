"""AutoCount integration provider (AC-13-01 / AC-13-04).

Registers into the CORE provider registry (``app/integrations``) as an ``erp``
connection, so AutoCount is configured through the same `/settings/integrations`
Resource shell as SMTP/S3 - no bespoke connection UI.

Two shapes deviate from the other providers, both forced by the vendor API:

* **No AppSecret.** Verified live: auth is a single ``POST /api/Server/Login``
  with an ``AppId`` header and ``{UserID, Password}``. The Postman collection's
  two-step ``Auth/Login`` → ``Server/Login`` flow does not exist.
* **No company field.** The server resolves the company from the ``AppId``
  header and returns ``DatabaseName``/``CompanyName`` on login - so the company
  is DISCOVERED and stored read-only, never entered by the operator (D16,
  foolproof-UI: never ask for something we can determine, and never let an
  operator type a value that will be silently overridden).

``test()`` names the failing STEP (AC-13-04). "Connection failed" catch-alls are
banned - the operator has to know whether to fix the URL, the AppId, or the
credentials.
"""
import time
from typing import Any, Dict, List, Optional

from app.integrations.base import TestResult

from .client import (
    AutoCountAppError,
    AutoCountAuthError,
    AutoCountClient,
    AutoCountError,
    AutoCountRelayError,
    AutoCountTransportError,
)
from .http_client import (
    OpenProbeError,
    assert_autocount_base_url_deliverable,
    probe_open_connection,
)

PROVIDER_KEY = "autocount"
CONNECTION_TYPE = "erp"

# AC-10-85 (live-replay Finding 1) - per-CONNECTION overrides for the open
# REST wrapper's own host-latency knobs, replacing the fixed module
# constants ``http_source.source.DEFAULT_PAGE_SIZE`` /
# ``http_source.client.DEFAULT_TIMEOUT_SECONDS`` used to always fall back
# to. Duplicated here (rather than imported) to avoid a circular import -
# ``http_source/source.py`` itself imports THIS module - and because these
# are the FORM SCHEMA's own bounds, independent of the runtime fallback
# value the source picks when a connection carries neither key at all.
PAGE_SIZE_FIELD_DEFAULT = 1000
PAGE_SIZE_FIELD_MIN = 50
PAGE_SIZE_FIELD_MAX = 1000
REQUEST_TIMEOUT_FIELD_DEFAULT = 90
REQUEST_TIMEOUT_FIELD_MAX = 100

# The two auth modes an ``autocount`` connection may carry (sprint-5/08,
# AC-08-01). ``basic`` is the vendor session-auth grammar (AppId/UserId/
# Password, today's ONLY behaviour); ``none`` is the open REST wrapper -
# base URL only, no credentials, never a login attempt.
AUTH_BASIC = "basic"
AUTH_NONE = "none"


def auth_mode(config: Dict[str, Any]) -> str:
    """``config.auth``, defaulted to ``basic`` for a legacy row that predates
    this field (AC-08-01) - never ``KeyError``, never a silent ``None``."""
    value = str((config or {}).get("auth") or "").strip().lower()
    return value if value in (AUTH_BASIC, AUTH_NONE) else AUTH_BASIC


def is_open_connection(conn: Any) -> bool:
    """Whether a stored ``Connection`` row is an open (no-auth) AutoCount
    connection - the ``autocount`` provider AND ``auth_mode == 'none'``.
    Any other provider, or a missing/legacy config, is never open."""
    if conn is None or getattr(conn, "provider", None) != PROVIDER_KEY:
        return False
    return auth_mode(conn.config_json or {}) == AUTH_NONE


def client_from_connection(
    config: Dict[str, Any],
    credentials: Dict[str, Any],
    *,
    transport: Optional[Any] = None,
) -> AutoCountClient:
    """Build a client from a connection's stored config + DECRYPTED credentials.

    Callers pass credentials already decrypted via ``app/secrets.py``
    (``decrypt_secret``, with ``InvalidToken`` caught as a clean reject) - this
    module never handles ciphertext or a module-local Fernet key.
    """
    return AutoCountClient(
        base_url=str(config.get("baseUrl", "")).strip(),
        app_id=str(credentials.get("appId") or config.get("appId") or "").strip(),
        user_id=str(config.get("userId", "")).strip(),
        password=str(credentials.get("password", "")),
        # Explicit per connection, never silently downgraded (plan §11).
        verify_tls=bool(config.get("verifyTls", True)),
        transport=transport,
    )


class AutoCountProvider:
    provider = PROVIDER_KEY
    type = CONNECTION_TYPE
    title = "AutoCount"
    description = (
        "Sync products, stock, suppliers, customers and documents with an on-premise "
        "AutoCount company. One connection per AutoCount company."
    )
    icon = "refresh-cw"
    test_label = "Test connection"
    # Connection check only - there is no meaningful targeted test for a read
    # integration (and a write probe against a customer's live ledger is not
    # something a Test button may ever do).
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        """Config schema driving the integrations form.

        ``auth`` leads (AC-08-01): ``basic`` is the vendor session-auth
        grammar (AppId/UserId/Password, today's ONLY behaviour before this
        field existed); ``none`` is the open REST wrapper - base URL only.
        The three credential fields carry ``showWhen`` so the form hides
        (and stops requiring) them when ``none`` is picked; ``baseUrl`` is
        always shown. No AppSecret (does not exist) and no company picker
        (discovered from the login response) - offering either would be
        asking the operator for something we cannot use.
        """
        return [
            {
                "key": "auth",
                "label": "Auth",
                "type": "select",
                "required": True,
                "default": AUTH_BASIC,
                "options": [
                    {"value": AUTH_BASIC, "label": "Basic auth (AppId + user + password)"},
                    {"value": AUTH_NONE, "label": "No auth"},
                ],
            },
            {
                "key": "baseUrl",
                "label": "AutoCount API base URL",
                "type": "text",
                "required": True,
                "placeholder": "https://autocount.customer.com",
            },
            {
                "key": "appId",
                "label": "AppId",
                "type": "password",
                "required": True,
                "secret": True,
                "showWhen": {"field": "auth", "values": [AUTH_BASIC]},
            },
            {
                "key": "userId",
                "label": "User ID",
                "type": "text",
                "required": True,
                "placeholder": "ADMIN",
                "showWhen": {"field": "auth", "values": [AUTH_BASIC]},
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "required": True,
                "secret": True,
                "showWhen": {"field": "auth", "values": [AUTH_BASIC]},
            },
            # AC-10-85 - the open REST wrapper's own host-latency knobs;
            # meaningless for the vendor session-auth flavour, which never
            # runs a page walk against this client, hence the `showWhen`.
            # BOTH default keys are declared on purpose: `default` (numeric)
            # is this field schema's own contract, and `defaultValue` (a
            # string) is the key the connection wizard's generic prefill
            # actually reads (`connection-schema.ts defaultsForProvider`) -
            # without it the operator would face a blank box instead of the
            # AC's stated 1000 / 90.
            {
                "key": "pageSize",
                "label": "Page size",
                "type": "number",
                "required": False,
                "default": PAGE_SIZE_FIELD_DEFAULT,
                "defaultValue": str(PAGE_SIZE_FIELD_DEFAULT),
                "min": PAGE_SIZE_FIELD_MIN,
                "max": PAGE_SIZE_FIELD_MAX,
                "showWhen": {"field": "auth", "values": [AUTH_NONE]},
            },
            {
                "key": "requestTimeoutSeconds",
                "label": "Request timeout (seconds)",
                "type": "number",
                "required": False,
                "default": REQUEST_TIMEOUT_FIELD_DEFAULT,
                "defaultValue": str(REQUEST_TIMEOUT_FIELD_DEFAULT),
                "max": REQUEST_TIMEOUT_FIELD_MAX,
                "showWhen": {"field": "auth", "values": [AUTH_NONE]},
            },
        ]

    def validate_config(self, config: Dict[str, Any]) -> Optional[str]:
        """S5 (sprint-5/08 review round 1) - the SAME scheme rule `test()`
        already applies, now also enforced at SAVE, not only when the
        operator happens to click Test. Blank is fine here (the `required`
        gate on `baseUrl` is the wizard's own job); only a present-but-bad
        scheme is rejected.

        AC-10-85 (live-replay Finding 1) - `pageSize`/`requestTimeoutSeconds`
        are range-checked the same way, naming the offending field so the
        422 is actionable.

        AC-10-58 M2 - the outbound SSRF guard also runs here, at save time
        (re-run again immediately before every actual request - see
        `http_source.client.HttpApiClient.get`)."""
        base_url = str((config or {}).get("baseUrl") or "").strip()
        if base_url and not base_url.lower().startswith(("http://", "https://")):
            return "The base URL must start with http:// or https://."

        page_size_raw = str((config or {}).get("pageSize") or "").strip()
        if page_size_raw:
            try:
                page_size_value = int(page_size_raw)
            except ValueError:
                return "pageSize must be a whole number."
            if not (PAGE_SIZE_FIELD_MIN <= page_size_value <= PAGE_SIZE_FIELD_MAX):
                return (
                    f"pageSize must be between {PAGE_SIZE_FIELD_MIN} and "
                    f"{PAGE_SIZE_FIELD_MAX}."
                )

        timeout_raw = str((config or {}).get("requestTimeoutSeconds") or "").strip()
        if timeout_raw:
            try:
                timeout_value = float(timeout_raw)
            except ValueError:
                return "requestTimeoutSeconds must be a number."
            if timeout_value <= 0 or timeout_value > REQUEST_TIMEOUT_FIELD_MAX:
                return (
                    f"requestTimeoutSeconds must be at most "
                    f"{REQUEST_TIMEOUT_FIELD_MAX} seconds."
                )

        # LAST, because it is the only check here that can touch the network
        # (the guard resolves the host to catch a name pointing at an internal
        # address): a plain out-of-range number is refused without paying for
        # a DNS lookup.
        if base_url:
            try:
                assert_autocount_base_url_deliverable(base_url)
            except OpenProbeError as exc:
                return f"baseUrl: {exc.message}"
        return None

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
        *,
        transport: Optional[Any] = None,
    ) -> TestResult:
        """Verify the connection - branching on ``auth_mode`` (AC-08-02).

        ``basic`` signs in ONCE (byte-for-byte the original behaviour) and
        echoes the DISCOVERED company so the operator can confirm the AppId
        selected the company they intended - the AppId is opaque, so this
        readback is the only way to catch "right credentials, wrong
        company". ``none`` NEVER attempts a login (credentials are not
        required and are ignored even if present): it GETs ``{baseUrl}/
        location`` and reports the row count, naming the failing STEP on any
        error - never the raw response body.
        """
        base_url = str(config.get("baseUrl", "")).strip()
        if not base_url:
            return TestResult(ok=False, message="Enter the AutoCount API base URL.")
        if not base_url.lower().startswith(("http://", "https://")):
            return TestResult(
                ok=False,
                message="The base URL must start with http:// or https://.",
            )

        if auth_mode(config) == AUTH_NONE:
            # AC-10-85 - the Test button reports the MEASURED probe latency
            # (never a canned "Reachable"), the ONE number that tells the
            # operator whether a legacy 30s or the new 90s ceiling is safe
            # for this wrapper's own real-world response time.
            started = time.monotonic()
            try:
                rows = probe_open_connection(base_url, transport=transport)
            except OpenProbeError as exc:
                return TestResult(ok=False, message=exc.message)
            elapsed_seconds = time.monotonic() - started
            count = len(rows)
            noun = "location" if count == 1 else "locations"
            return TestResult(
                ok=True,
                message=f"Reached in {elapsed_seconds:.2f} s, {count} {noun}.",
            )

        client = client_from_connection(config, credentials, transport=transport)
        try:
            session = client.login()
        except AutoCountTransportError as exc:
            # Unreachable / timeout - distinct from an auth rejection.
            return TestResult(ok=False, message=exc.message)
        except AutoCountAuthError as exc:
            return TestResult(
                ok=False,
                message=(
                    f"AutoCount rejected the sign-in: {exc.message} Check the User ID "
                    f"and Password."
                ),
            )
        except AutoCountRelayError as exc:
            # A bad AppId surfaces here - the relay faults rather than replying
            # cleanly. The AppId is the actionable thing, so name it. The raw
            # .NET stack trace stays in exc.detail (log only), never shown.
            return TestResult(
                ok=False,
                message=(
                    f"Signed in to {base_url} but AutoCount returned an internal error. "
                    f"This usually means the AppId is not recognised. ({exc.message})"
                ),
            )
        except AutoCountAppError as exc:
            return TestResult(ok=False, message=exc.message)
        except AutoCountError as exc:  # defensive - never leak a raw traceback
            return TestResult(ok=False, message=exc.message)
        finally:
            client.close()

        company = session.company_name or session.database_name
        if not company:
            return TestResult(
                ok=True,
                message=(
                    "Signed in successfully, but AutoCount did not report a company "
                    "name. Confirm the AppId maps to the intended company database."
                ),
            )
        return TestResult(
            ok=True,
            message=f"Connected to {company} ({session.database_name}).",
        )

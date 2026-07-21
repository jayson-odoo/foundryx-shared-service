"""AutoCount session-auth HTTP client (AC-13-03 / AC-13-04 / AC-13-04a).

    !!  EVERY RULE HERE WAS VERIFIED AGAINST THE LIVE DEMO INSTANCE (2026-07-21). !!
    !!  The vendor Postman collection is stale and partly WRONG — where the two   !!
    !!  disagree, this file is right and the collection is not.                   !!

Four things about this API are counter-intuitive enough to cost a diagnostic
cycle each, so they are stated up front:

1. **Use ``JWTToken``, not ``Token``.** ``POST /api/Server/Login`` returns a BARE
   JSON ARRAY whose ``[0]`` carries BOTH a ``Token`` (a GUID) and a ``JWTToken``.
   The collection stores the GUID in ``{{token}}``; it is rejected by every
   endpoint with a misleading ``HTTP 500 "Stream was not readable."`` that looks
   exactly like a broken server. Send the JWT as a BARE ``Authorization:
   <JWTToken>`` header — **no ``Bearer`` prefix, not ``X-API-Key``.**

2. **Success is ``Status == "Success"``.** NOT the HTTP status code (business
   failures come back ``HTTP 200``) and NOT the presence of ``ResultTable``
   (which is present-but-EMPTY on failure). Testing for ``ResultTable`` reads a
   failure as an empty-but-successful fetch — silent wrong data.

3. **There is no 401.** An invalid or expired token returns the same
   ``HTTP 500 "Stream was not readable."`` as any other relay fault, so expiry is
   not reliably detectable. Defence is twofold: proactive age-based re-login
   (primary) plus exactly ONE re-login-and-retry on that specific error
   (backstop). Slice-1 calls are reads, so the retry is safe.

4. **A malformed filter is SILENTLY IGNORED** — verified: ``{"DocNo":"not-an-array"}``
   returns the ENTIRE table with ``Status:"Success"``. A bad filter degrades to a
   full table scan indistinguishable from a successful delta. Hence
   ``validate_read_filter`` before send and ``assert_window`` after (AC-13-04a).

Company is DISCOVERED, never configured: login returns ``DatabaseName`` and
``CompanyName``. There is no company parameter anywhere — the server resolves it
from the ``AppId`` header, so **AppId IS the company selector** (D16).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.integrations.masking import mask_payload

logger = logging.getLogger(__name__)

# The relay's catch-all fault string. It is what an invalid/expired token
# produces, and ALSO what several unrelated faults produce — it is not a
# reliable expiry signal, only a "worth one re-login" signal.
STREAM_NOT_READABLE = "stream was not readable"

# Re-login this long after the token was issued, before it can go stale. There
# is no 401 to react to, so this proactive renewal is the PRIMARY defence.
DEFAULT_TOKEN_MAX_AGE_SECONDS = 20 * 60
DEFAULT_TIMEOUT_SECONDS = 30.0

# The vendor's date format for read filters. Three formats appear in RESPONSES
# (see the plan's hazard table); requests use this one.
FILTER_DATE_FORMAT = "%Y/%m/%d"

# Read filters take LIST values for their identifier keys. A scalar here is the
# silent-full-scan trap (rule 4).
_LIST_FILTER_KEYS = ("DocNo", "AccNo", "ItemCode", "DebtorCode", "CreditorCode")
_DATE_FILTER_KEYS = (
    "DateFrom", "DateTo",
    "CreatedTimeFrom", "CreatedTimeTo",
    "LastModifiedFrom", "LastModifiedTo",
)


class AutoCountError(Exception):
    """Base for every AutoCount failure. ``message`` is safe to show an operator
    (never a raw .NET stack trace)."""

    def __init__(self, message: str, *, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        # Full technical detail for the log; NEVER surfaced to a user.
        self.detail = detail


class AutoCountAuthError(AutoCountError):
    """Login was rejected — bad UserID/Password, or a bad AppId."""


class AutoCountAppError(AutoCountError):
    """App-level failure: ``HTTP 200`` + ``{"Status":"Fail","Message":…}``.
    ``Message`` is the vendor's own business explanation — surface it verbatim."""


class AutoCountRelayError(AutoCountError):
    """Relay-level failure: ``HTTP 500`` + a .NET exception object
    (``ClassName``/``Message``/``StackTraceString``). The stack trace goes to the
    log only; the operator gets a mapped message."""

    def __init__(self, message: str, *, detail: Optional[str] = None, raw_message: str = ""):
        super().__init__(message, detail=detail)
        # The .NET exception's own Message — used to recognise the
        # "Stream was not readable." case that warrants a re-login retry.
        self.raw_message = raw_message


class AutoCountTransportError(AutoCountError):
    """The host could not be reached at all — DNS, refused, TLS, or timeout.
    Distinct from an auth rejection (AC-13-04)."""


class AutoCountFilterError(AutoCountError):
    """A read filter that AutoCount would silently ignore (AC-13-04a). Raised
    BEFORE the request leaves us — never let a full table scan masquerade as a
    delta."""


class AutoCountWindowError(AutoCountError):
    """The returned set is inconsistent with the requested window — evidence the
    filter was ignored server-side. Fails loudly (AC-13-04a)."""


@dataclass
class Session:
    """A held login. ``jwt_token`` is the credential actually sent; ``token``
    (the GUID) is captured only so it is never accidentally used."""

    jwt_token: str
    token: str
    database_name: str
    company_name: str
    issued_at: datetime

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        return ((now or datetime.now(timezone.utc)) - self.issued_at).total_seconds()

    def is_stale(self, max_age_seconds: float, now: Optional[datetime] = None) -> bool:
        return self.age_seconds(now) >= max_age_seconds


def _safe(value: Any) -> str:
    """A string safe to log/surface — secrets masked, length-capped."""
    return str(mask_payload(value))[:2000]


def validate_read_filter(payload: Dict[str, Any]) -> None:
    """Reject a filter AutoCount would silently ignore (AC-13-04a).

    Verified live: ``{"DocNo":"not-an-array"}`` returns the ENTIRE table with
    ``Status:"Success"``. There is no server-side error to catch, so this is the
    ONLY line of defence against a full scan reading as a narrow fetch.
    """
    if not isinstance(payload, dict):
        raise AutoCountFilterError("Read filter must be an object.")

    for key in _LIST_FILTER_KEYS:
        if key in payload and not isinstance(payload[key], (list, tuple)):
            raise AutoCountFilterError(
                f"Read filter '{key}' must be a list (AutoCount silently ignores "
                f"a non-list and returns the entire table)."
            )

    for key in _DATE_FILTER_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise AutoCountFilterError(
                f"Read filter '{key}' must be a non-empty date string."
            )

    count = payload.get("RecordCount")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count <= 0):
        raise AutoCountFilterError("Read filter 'RecordCount' must be a positive integer.")


def parse_last_modified(value: Any) -> Optional[datetime]:
    """Parse a vendor ``LastModified`` into an aware-UTC datetime.

    Three formats occur in responses (plan hazard table). Returns None when the
    value is absent or unparseable — the CALLER decides whether that is fatal
    (``assert_window`` treats it as fatal, since an unverifiable record cannot be
    confirmed inside the requested window)."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:  # ISO-8601 fallback (e.g. "2024-09-15T16:37:34Z")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def assert_window(
    records: Sequence[Dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    field_name: str = "LastModified",
) -> None:
    """Assert every record falls inside the requested window (AC-13-04a).

    This is the post-hoc half of the silent-ignored-filter defence: if the server
    ignored our ``LastModifiedFrom``/``To`` we get the whole table back with
    ``Status:"Success"``, and the ONLY evidence is records outside the window.
    Fail loudly rather than advance a watermark over data we never asked for.

    ``start``/``end`` are aware-UTC. **Both bounds are widened to whole DAYS**
    because the vendor filter is date-only (``FILTER_DATE_FORMAT``): asking for
    ``LastModifiedTo=2026/07/21`` legitimately returns a record stamped
    ``2026/07/21 16:37:34``. Comparing against the caller's exact instant would
    reject correct data — a false alarm on the very first real sync. The
    comparison must model what the SERVER was actually asked, not what the caller
    had in mind.
    """
    start = start.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = end.astimezone(timezone.utc).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    for record in records:
        raw = record.get(field_name)
        stamp = parse_last_modified(raw)
        if stamp is None:
            raise AutoCountWindowError(
                f"A returned record has no parseable '{field_name}' "
                f"({_safe(raw)}) — the requested window cannot be verified."
            )
        if stamp < start or stamp > end:
            raise AutoCountWindowError(
                f"AutoCount returned a record modified {stamp.isoformat()}, outside "
                f"the requested window {start.isoformat()}..{end.isoformat()} — the "
                f"filter was ignored and this is a full table scan, not a delta."
            )


class AutoCountClient:
    """One client per (connection, company). Holds a session; re-logs in on age
    or on the one ambiguous relay error that means "probably expired".

    ``transport`` is the httpx client seam — tests inject a mock; nothing here
    ever touches a live instance under test.
    """

    def __init__(
        self,
        *,
        base_url: str,
        app_id: str,
        user_id: str,
        password: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        token_max_age_seconds: float = DEFAULT_TOKEN_MAX_AGE_SECONDS,
        verify_tls: bool = True,
        transport: Optional[httpx.Client] = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.app_id = app_id
        self._user_id = user_id
        self._password = password
        self.timeout_seconds = timeout_seconds
        self.token_max_age_seconds = token_max_age_seconds
        # Customer endpoints may be plain HTTP or self-signed (plan §11) — the
        # policy is EXPLICIT per connection, never silently downgraded.
        self.verify_tls = verify_tls
        self._transport = transport
        self.session: Optional[Session] = None

    # ── transport ──────────────────────────────────────────────────────────

    @property
    def _client(self) -> httpx.Client:
        if self._transport is None:
            self._transport = httpx.Client(
                timeout=self.timeout_seconds, verify=self.verify_tls
            )
        return self._transport

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def __enter__(self) -> "AutoCountClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _post(self, path: str, *, headers: Dict[str, str], json_body: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            return self._client.post(url, headers=headers, json=json_body)
        except httpx.TimeoutException as exc:
            raise AutoCountTransportError(
                f"AutoCount at {self.base_url} did not respond within "
                f"{self.timeout_seconds:g}s.",
                detail=str(exc),
            ) from exc
        except httpx.HTTPError as exc:
            raise AutoCountTransportError(
                f"Could not reach AutoCount at {self.base_url} ({type(exc).__name__}). "
                f"Check the base URL, that the host is running, and that our egress "
                f"IP is whitelisted.",
                detail=str(exc),
            ) from exc

    # ── envelope handling ──────────────────────────────────────────────────

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise AutoCountRelayError(
                "AutoCount returned a response that was not JSON.",
                # Through ``_safe`` like every other detail in this file: a relay
                # fault can echo the REQUEST back, and the request to
                # ``/api/Server/Login`` is ``{UserID, Password}``.
                detail=_safe(f"HTTP {response.status_code}: {response.text[:1000]}"),
            ) from exc

    @classmethod
    def _raise_relay(cls, response: httpx.Response) -> None:
        """Relay-level failure: HTTP 500 + a .NET exception object.

        The .NET ``StackTraceString`` NEVER reaches an operator (AC-13-04) — it
        goes to ``detail`` for the log only.

            !!  ``detail`` IS INTENDED TO BE LOGGED, SO IT IS MASKED.  !!

        A .NET relay fault routinely echoes the REQUEST inside its exception
        text, and the request to ``/api/Server/Login`` is literally
        ``{"UserID": ..., "Password": ...}`` under an ``AppId`` header. So every
        path out of here goes through ``_safe`` (``mask_payload`` + length cap),
        exactly like the other seven ``detail=`` sites in this file.

        Where the body PARSES, it is masked STRUCTURALLY first — that redacts a
        ``Password``/``AppId`` key anywhere in the .NET object graph, which
        masking the composed string could not do. Residual limitation, stated
        rather than hidden: a credential embedded in free-form trace TEXT
        (``"...Login failed for AppId=xyz..."``) is not key-addressable and
        survives; the structural pass is the defence that scales.
        """
        raw_message = ""
        detail = _safe(f"HTTP {response.status_code}: {response.text[:2000]}")
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            # Mask the object graph FIRST, then compose out of the masked copy —
            # so a ``Password``/``AppId`` key nested anywhere in the .NET
            # exception is already redacted by the time it reaches a string, in
            # the OPERATOR-facing ``friendly``/``raw_message`` as well as in
            # ``detail``.
            masked = mask_payload(body)
            raw_message = str(masked.get("Message") or "")
            class_name = str(masked.get("ClassName") or "")
            detail = _safe(
                f"HTTP {response.status_code} {class_name}: {raw_message}\n"
                f"{str(masked.get('StackTraceString') or '')[:2000]}"
            )
        friendly = (
            f"AutoCount returned an internal error (HTTP {response.status_code})"
            + (f": {raw_message}" if raw_message else ".")
        )
        raise AutoCountRelayError(friendly, detail=detail, raw_message=raw_message)

    @classmethod
    def _unwrap(cls, response: httpx.Response) -> Dict[str, Any]:
        """HTTP response → the success envelope, or the right exception.

        Success is ``Status == "Success"`` — NEVER the HTTP code, NEVER the
        presence of ``ResultTable`` (present-but-empty on failure).
        """
        if response.status_code >= 500:
            cls._raise_relay(response)

        body = cls._json(response)
        if not isinstance(body, dict):
            raise AutoCountAppError(
                "AutoCount returned an unexpected response shape.",
                detail=_safe(body),
            )

        status = str(body.get("Status") or "")
        if status.lower() != "success":
            message = str(body.get("Message") or "").strip()
            raise AutoCountAppError(
                message or "AutoCount rejected the request without giving a reason.",
                detail=_safe(body),
            )
        return body

    # ── auth ───────────────────────────────────────────────────────────────

    def login(self) -> Session:
        """``POST /api/Server/Login`` — the ONE auth step (there is no
        ``/api/Auth/Login`` and no AppSecret).

        The response is a BARE JSON ARRAY; the session lives at ``[0]``.
        """
        response = self._post(
            "/api/Server/Login",
            headers={"AppId": self.app_id, "Content-Type": "application/json"},
            # Password is in the body — never log this dict unmasked.
            json_body={"UserID": self._user_id, "Password": self._password},
        )

        if response.status_code >= 500:
            # A relay fault at login is indistinguishable from a bad AppId in
            # shape, but the AppId is the thing the operator can actually fix.
            self._raise_relay(response)

        body = self._json(response)
        # A bare ARRAY is the success shape. A dict here is an error envelope.
        if isinstance(body, dict):
            message = str(body.get("Message") or "").strip()
            raise AutoCountAuthError(
                message or "AutoCount rejected the sign-in.", detail=_safe(body)
            )
        if not isinstance(body, list) or not body or not isinstance(body[0], dict):
            raise AutoCountAuthError(
                "AutoCount's sign-in response was not the expected array.",
                detail=_safe(body),
            )

        entry = body[0]
        jwt_token = str(entry.get("JWTToken") or "").strip()
        if not jwt_token:
            # Guard the exact trap: a response carrying only the GUID would
            # otherwise sail through and then 500 on every subsequent call.
            raise AutoCountAuthError(
                "AutoCount's sign-in response carried no JWTToken. The 'Token' GUID "
                "is NOT usable as a credential — every endpoint rejects it.",
                detail=_safe({k: v for k, v in entry.items() if k != "JWTToken"}),
            )

        self.session = Session(
            jwt_token=jwt_token,
            token=str(entry.get("Token") or ""),
            # Company is DISCOVERED here, never configured (D16).
            database_name=str(entry.get("DatabaseName") or ""),
            company_name=str(entry.get("CompanyName") or ""),
            issued_at=datetime.now(timezone.utc),
        )
        return self.session

    def _ensure_session(self) -> Session:
        """Return a fresh-enough session, re-logging in proactively on age.

        There is no 401 to react to, so age is the primary expiry defence.
        """
        if self.session is None:
            return self.login()
        if self.session.is_stale(self.token_max_age_seconds):
            logger.debug(
                "AutoCount token exceeded max age (%.0fs) — re-logging in.",
                self.token_max_age_seconds,
            )
            return self.login()
        return self.session

    def auth_headers(self) -> Dict[str, str]:
        """The credential header for every non-login call.

        BARE ``Authorization: <JWTToken>``. No ``Bearer`` prefix. Not
        ``X-API-Key``. The ``Token`` GUID is never sent.
        """
        session = self._ensure_session()
        return {
            "AppId": self.app_id,
            "Authorization": session.jwt_token,
            "Content-Type": "application/json",
        }

    # ── calls ──────────────────────────────────────────────────────────────

    def call(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """One authenticated POST, with EXACTLY ONE re-login-and-retry on the
        ambiguous ``"Stream was not readable."`` relay error.

        The retry counter is PER CALL (a local), never shared state — a session
        making many calls must not exhaust one global retry budget, and one bad
        call must never loop.
        """
        attempted_relogin = False
        while True:
            response = self._post(path, headers=self.auth_headers(), json_body=payload)
            try:
                return self._unwrap(response)
            except AutoCountRelayError as exc:
                is_probably_expired = STREAM_NOT_READABLE in exc.raw_message.lower()
                if not is_probably_expired or attempted_relogin:
                    raise
                # This error is what an invalid/expired token produces (there is
                # no 401). One re-login + retry; reads are idempotent so it is
                # safe. If it fails again the error propagates untouched.
                logger.info(
                    "AutoCount returned the ambiguous relay error on %s — "
                    "re-logging in and retrying once.",
                    path,
                )
                attempted_relogin = True
                self.session = None
                self.login()

    def read(
        self,
        entity: str,
        payload: Dict[str, Any],
        *,
        window: Optional["tuple[datetime, datetime]"] = None,
    ) -> List[Dict[str, Any]]:
        """``POST /api/{Entity}/Get{Entity}`` — the uniform read.

        Validates the filter BEFORE sending (a malformed one is silently ignored
        and returns the whole table) and, when a window is given, asserts every
        returned record falls inside it. Both halves of AC-13-04a.
        """
        validate_read_filter(payload)
        body = self.call(f"/api/{entity}/Get{entity}", payload)

        result = body.get("ResultTable")
        if result is None:
            result = []
        if not isinstance(result, list):
            raise AutoCountAppError(
                "AutoCount returned a ResultTable that was not a list.",
                detail=_safe(result),
            )
        records = [row for row in result if isinstance(row, dict)]

        if window is not None:
            assert_window(records, start=window[0], end=window[1])
        return records


def build_read_filter(
    *,
    record_count: int,
    last_modified_from: Optional[datetime] = None,
    last_modified_to: Optional[datetime] = None,
    doc_numbers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build a well-formed read filter (the shape ``validate_read_filter`` accepts).

    Callers should prefer this over hand-building a dict — the identifier keys
    MUST be lists, and that is precisely the mistake AutoCount does not report.
    """
    payload: Dict[str, Any] = {
        "DocNo": list(doc_numbers or []),
        "RecordCount": record_count,
    }
    if last_modified_from is not None:
        payload["LastModifiedFrom"] = last_modified_from.strftime(FILTER_DATE_FORMAT)
    if last_modified_to is not None:
        payload["LastModifiedTo"] = last_modified_to.strftime(FILTER_DATE_FORMAT)
    validate_read_filter(payload)
    return payload

"""``RespondIoClient`` - the ONE HTTP seam to the respond.io Developer API v2
(plan 33 §5.1, D-A6-5/D-A6-6).

Header-driven rate limiting (no hardcoded numeric limit - the vendor
publishes none): self-throttles at a configurable ``requests_per_second``,
honours ``retry-after`` on 429 exactly, reads ``x-ratelimit-limit`` /
``x-ratelimit-remaining`` for callers that want to log them, retries 429 and
5xx with exponential backoff + jitter up to 5 attempts, and halves its own
rate for the rest of the run after a 4th CONSECUTIVE 429 (reported through
``on_milestone`` - S2's job service turns that into a milestone log line).

A non-429 4xx (401/403/404/422/...) raises ``RespondIoError`` carrying the
vendor's ``{code, message}`` body untouched - callers map it (the provider's
``test()`` maps 401/403 to a clean, fixed message; a job-phase caller maps it
to a per-entity report row, never an unhandled 500 - AC-MIG-16).

Tests inject ``client=httpx.Client(transport=httpx.MockTransport(handler))``
and ``sleep=`` / ``rand=`` fakes (the pattern already used for
``WhatsAppCloudAdapter``, ``tests/test_omnichannel.py``) so retry/backoff/
throttle pacing is asserted deterministically with zero real waiting.
"""
import logging
import random
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.respond.io/v2"
DEFAULT_REQUESTS_PER_SECOND = 4
MAX_REQUESTS_PER_SECOND = 20
MIN_REQUESTS_PER_SECOND = 0.1
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 5
# Review round 1, finding B3 - a hard ceiling on the vendor cursor walk. A
# vendor that returns the SAME cursor twice, a constant cursor, or an empty
# `items` page WITH a cursor (all observable failure modes on a paginated
# API this codebase does not control) would otherwise loop forever: unbounded
# API calls, an unkillable background job (the abort check lives OUTSIDE this
# generator, in the job service's own per-page loop), and a pinned DB
# session. Far more pages than any real migration should ever need.
MAX_PAGES = 100_000
# Halve our own rate after this many CONSECUTIVE 429s (D-A6-5).
RATE_HALVE_THRESHOLD = 4
_BACKOFF_BASE_SECONDS = 0.5

MilestoneFn = Callable[[str], None]


class RespondIoError(Exception):
    """A non-retryable (or retry-exhausted) respond.io API failure. Carries
    the vendor's OWN ``{code, message}`` body - never a raw traceback, DSN or
    the access token (AC-MIG-13/16)."""

    def __init__(self, message: str, *, status_code: int, code: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def _default_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


class RespondIoClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_token: str = "",
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.Client] = None,
        on_milestone: Optional[MilestoneFn] = None,
        sleep: Callable[[float], None] = _default_sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
    ):
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._token = api_token or ""
        self._rps = _clamp_rps(requests_per_second)
        self._timeout = timeout
        self._client = client
        self._on_milestone = on_milestone or (lambda _msg: None)
        self._sleep = sleep
        self._monotonic = monotonic
        self._rand = rand
        self._last_request_at: Optional[float] = None
        self._consecutive_429 = 0
        # Last-seen rate headers (str|None) - a caller (S2's job service) can
        # read these for its own milestone/telemetry lines.
        self.last_rate_limit: Optional[str] = None
        self.last_rate_remaining: Optional[str] = None

    @classmethod
    def from_connection(
        cls,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        client: Optional[httpx.Client] = None,
        on_milestone: Optional[MilestoneFn] = None,
    ) -> "RespondIoClient":
        """Build a client from a saved ``respondio`` connection's
        ``config_json``/decrypted ``credentials_json`` (both plain-string
        wire values - ``ConnectionOut.config`` is ``Dict[str, str]``)."""
        base_url = str(config.get("baseUrl") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        try:
            rps = float(config.get("requestsPerSecond") or DEFAULT_REQUESTS_PER_SECOND)
        except (TypeError, ValueError):
            rps = DEFAULT_REQUESTS_PER_SECOND
        return cls(
            base_url=base_url,
            api_token=str(credentials.get("apiToken", "")),
            requests_per_second=rps,
            client=client,
            on_milestone=on_milestone,
        )

    # ── transport ──────────────────────────────────────────────────────────

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._timeout)

    def _throttle(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self._monotonic()
            return
        min_interval = 1.0 / self._rps
        elapsed = self._monotonic() - self._last_request_at
        wait = min_interval - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _backoff_seconds(self, attempt: int) -> float:
        base = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
        return base + (self._rand() * base)

    def _retry_after_seconds(self, resp: httpx.Response) -> Optional[float]:
        raw = resp.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(float(raw), 0.0)
        except ValueError:
            return None  # an HTTP-date form - fall back to our own backoff

    def _error_from(self, resp: httpx.Response) -> RespondIoError:
        body: Dict[str, Any] = {}
        if resp.content:
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    body = parsed
            except ValueError:
                body = {}
        message = str(body.get("message") or f"respond.io returned {resp.status_code}.")
        return RespondIoError(message, status_code=resp.status_code, code=body.get("code"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        client = self._http()
        try:
            attempt = 0
            while True:
                attempt += 1
                self._throttle()
                try:
                    resp = client.request(
                        method, url, headers=headers, params=params, json=json_body
                    )
                except httpx.HTTPError as exc:
                    if attempt >= MAX_ATTEMPTS:
                        raise RespondIoError(
                            f"Could not reach respond.io: {exc}", status_code=0
                        ) from exc
                    self._sleep(self._backoff_seconds(attempt))
                    continue

                self.last_rate_limit = resp.headers.get("x-ratelimit-limit")
                self.last_rate_remaining = resp.headers.get("x-ratelimit-remaining")

                if resp.status_code == 429:
                    self._consecutive_429 += 1
                    if self._consecutive_429 == RATE_HALVE_THRESHOLD:
                        halved = _clamp_rps(self._rps / 2)
                        self._on_milestone(
                            f"respond.io rate limit hit {RATE_HALVE_THRESHOLD} times in a "
                            f"row - halving our own rate from {self._rps:.2f} to "
                            f"{halved:.2f} requests/second for the rest of this run."
                        )
                        self._rps = halved
                    if attempt >= MAX_ATTEMPTS:
                        raise self._error_from(resp)
                    retry_after = self._retry_after_seconds(resp)
                    self._sleep(
                        retry_after if retry_after is not None else self._backoff_seconds(attempt)
                    )
                    continue

                if resp.status_code >= 500:
                    if attempt >= MAX_ATTEMPTS:
                        raise self._error_from(resp)
                    self._sleep(self._backoff_seconds(attempt))
                    continue

                self._consecutive_429 = 0
                if resp.status_code >= 400:
                    raise self._error_from(resp)
                if not resp.content:
                    return {}
                data = resp.json()
                return data if isinstance(data, dict) else {}
        finally:
            if self._client is None:
                client.close()

    def _paginated(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        for items, _next_cursor in self._paginated_pages(
            method, path, params=params, json_body=json_body, limit=limit
        ):
            for item in items:
                yield item

    def _paginated_pages(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Iterator[tuple]:
        """PAGE-granular walk (plan 33 S2, AC-MIG-22): yields
        ``(items, next_cursor)`` per page instead of flattening - the job
        service checkpoints ``cursor_json`` after EVERY page using the
        ``next_cursor`` this yields, and a crash-resume passes its last stored
        cursor back in as ``start_cursor`` to continue without re-walking
        already-processed pages. ``next_cursor`` is ``None`` on the LAST page
        (mirrors the vendor's own ``pagination.next`` absence).

        Review round 1, finding B3 - three termination guards, none of which
        the vendor's own contract rules out: (1) the returned ``next``
        equals the cursor just REQUESTED (a vendor stuck on the same page);
        (2) an empty ``items`` page that STILL carries a cursor (nothing left
        to walk, but the vendor never said so); (3) ``MAX_PAGES`` as an
        absolute ceiling, logged as a milestone so it surfaces on the job's
        detail page rather than looking like a silent early stop."""
        base_params = dict(params or {})
        base_params["limit"] = limit
        cursor: Optional[str] = start_cursor
        pages = 0
        while True:
            requested_cursor = cursor
            page_params = dict(base_params)
            if cursor:
                page_params["cursorId"] = cursor
            data = self._request(method, path, params=page_params, json_body=json_body)
            items = data.get("items") or []
            cursor = ((data.get("pagination") or {}).get("next")) or None
            pages += 1

            if cursor is not None and cursor == requested_cursor:
                self._on_milestone(
                    f"respond.io returned the same pagination cursor twice on {path} - "
                    "stopping this walk rather than looping forever."
                )
                yield items, None
                break
            if not items and cursor:
                self._on_milestone(
                    f"respond.io returned an empty page with a cursor still set on {path} - "
                    "treating this as the end of the walk."
                )
                yield items, None
                break
            if pages >= MAX_PAGES:
                self._on_milestone(
                    f"Reached the {MAX_PAGES}-page ceiling on {path} - stopping this walk; "
                    "some records may not have been migrated."
                )
                yield items, None
                break

            yield items, cursor
            if not cursor:
                break

    # ── connection test ─────────────────────────────────────────────────────

    def ping(self) -> Dict[str, Any]:
        """``GET /space/channel`` with a single-item page - the cheapest real
        call that proves the token AND the plan tier (AC-MIG-13)."""
        return self._request("GET", "/space/channel", params={"limit": 1})

    # ── preflight reads (AC-MIG-14) ─────────────────────────────────────────

    def list_space_channels(self) -> List[Dict[str, Any]]:
        return list(self._paginated("GET", "/space/channel"))

    def list_space_users(self) -> List[Dict[str, Any]]:
        return list(self._paginated("GET", "/space/user"))

    def list_custom_fields(self) -> List[Dict[str, Any]]:
        return list(self._paginated("GET", "/space/custom_field"))

    def list_contacts(
        self,
        *,
        timezone: str,
        search: Optional[str] = None,
        filter_: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        """``POST /contact/list`` - the preflight's read-only distinct-
        lifecycle pass (S1). ``timezone`` is REQUIRED by the vendor
        (plan §5.1). S2's resumable contacts WALK uses
        ``list_contacts_pages`` below instead (page-granular, resumable)."""
        body: Dict[str, Any] = {"timezone": timezone}
        if search:
            body["search"] = search
        if filter_:
            body["filter"] = filter_
        return self._paginated("POST", "/contact/list", json_body=body, limit=limit)

    def list_contacts_pages(
        self,
        *,
        timezone: str,
        search: Optional[str] = None,
        filter_: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Iterator[tuple]:
        """``POST /contact/list``, PAGE-granular (plan 33 S2, AC-MIG-22) -
        yields ``(items, next_cursor)`` so the migration job can write
        ``cursor_json`` after EVERY page and crash-resume from
        ``start_cursor`` without re-processing an already-completed page."""
        body: Dict[str, Any] = {"timezone": timezone}
        if search:
            body["search"] = search
        if filter_:
            body["filter"] = filter_
        return self._paginated_pages(
            "POST", "/contact/list", json_body=body, limit=limit, start_cursor=start_cursor
        )

    # ── S3 - identities + message history (AC-MIG-30/32, plan §5.1) ─────────

    def get_contact(self, identifier: str) -> Dict[str, Any]:
        """``GET /contact/{identifier}`` - a targeted re-fetch (plan §5.1's
        own "used for" note), consumed by the messages phase purely for the
        source ``contact.created_at`` D-A6-9 fallback. A single-resource GET,
        so (unlike every list call) this is NOT the ``{items,pagination}``
        envelope - the object comes back bare."""
        return self._request("GET", f"/contact/{identifier}")

    def get_contact_channels(self, identifier: str) -> List[Dict[str, Any]]:
        """``GET /contact/{identifier}/channels`` (AC-MIG-30) - the plan's own
        contract table lists no pagination for this call (a contact's channel
        count is small and bounded, unlike its message history), but every
        OTHER list call in this API answers the same ``{items,...}`` envelope,
        so this reads through the same envelope for consistency (S1's own
        risk note: a shape mismatch is a fix here, not a redesign)."""
        data = self._request("GET", f"/contact/{identifier}/channels")
        return list(data.get("items") or [])

    def list_messages_pages(
        self,
        identifier: str,
        *,
        limit: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Iterator[tuple]:
        """``GET /contact/{identifier}/message/list`` (AC-MIG-32), PAGE-
        granular - mirrors ``list_contacts_pages`` exactly (yields
        ``(items, next_cursor)`` so the messages phase can checkpoint and
        crash-resume mid-contact)."""
        return self._paginated_pages(
            "GET", f"/contact/{identifier}/message/list", limit=limit, start_cursor=start_cursor
        )


def _clamp_rps(value: float) -> float:
    try:
        rps = float(value)
    except (TypeError, ValueError):
        rps = DEFAULT_REQUESTS_PER_SECOND
    return max(MIN_REQUESTS_PER_SECOND, min(rps, MAX_REQUESTS_PER_SECOND))

"""The open (no-auth) AutoCount REST probe - a single ``GET`` used by the
provider's Test button (``auth == "none"``) AND open-company onboarding
(``CompanyService.create_from_open_connection``).

Deliberately tiny and separate from ``http_source/client.py`` (S3): that
module is the PAGED extraction transport a task runs against; this one is a
single reachability check with no session state, shared so the two callers
can never disagree about what "reachable" means.

Never attempts a login (there is nothing to log in to), never echoes a
response body beyond a bounded row count, and never persists anything.
"""
from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.url_guard import UrlGuardError, validate_public_url

# 10s per AC-08-02 - a probe, not an extraction; a slow/hung wrapper must
# fail fast rather than hold up the Test button or the create form.
OPEN_PROBE_TIMEOUT_SECONDS = 10.0

# sprint-5/10 confirm-3 B1 - the egress guard's scheme allow-list for THIS
# provider (unlike the house guard's every other caller, which stays
# https-only): a real AutoCount open-REST wrapper is routinely deployed
# behind plain http:// on an operator's own network, and AC-08-03/provider.py
# have always told the operator "http:// or https://" - the guard used to
# quietly refuse the http half of that promise. The TARGET restriction
# (private/loopback/link-local/reserved/multicast/unspecified, by literal or
# by DNS resolution) is unchanged for either scheme.
ALLOWED_BASE_URL_SCHEMES = ("http", "https")


class OpenProbeError(Exception):
    """The open-connection probe failed. ``message`` names the failing STEP
    (reachability / not JSON / an HTTP status) and is always operator-safe -
    never the raw response body (AC-08-02)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def get_http_transport() -> Optional[httpx.Client]:
    """FastAPI dependency seam (mirrors ``get_db``) for every router handler
    that ends up making a live open-API call (open-company create, the
    ``/autocount/http/preview`` route).

    Production never overrides this - it returns ``None``, meaning "build a
    real ``httpx.Client``". Tests override it via
    ``app.dependency_overrides[get_http_transport] = lambda: stub_client``
    so a ROUTE-level test (``client.post(...)``) can prove the real
    Router -> Service -> Service dispatch without EVER reaching
    ``hapi.sorento.cc.cd`` (sprint-5/08 review round 1, B4 - a bare
    ``monkeypatch`` of the transport-building function would work too, but
    this is the SAME seam every service method already accepts
    (``transport=``), just exposed to FastAPI's own DI so a router test
    does not need to reach into service internals).
    """
    return None


def _is_dev_local_host(host: str) -> bool:
    """The ONE dev-only carve-out for the egress guard below
    (``ENVIRONMENT=development``, mirrors ``modules.omnichannel.routers.
    webhooks._signature_valid``'s own fail-open-in-dev shape, BL-SS-166):
    a bare ``localhost``/``127.0.0.1`` (or any other ``127.*`` loopback) -
    never a broader private range, and never outside development - so a
    local ``http://localhost:PORT`` AutoCount wrapper still resolves for
    live-verify/E2E without opening up real internal-network targets."""
    lowered = (host or "").strip().lower()
    return lowered in ("localhost", "127.0.0.1") or lowered.startswith("127.")


def assert_autocount_base_url_deliverable(base_url: str) -> None:
    """AC-10-58 M2 - the outbound-egress guard: every AutoCount open-REST
    ``baseUrl`` is re-checked against the house SSRF guard
    (``app.services.url_guard.validate_public_url``) immediately before it is
    used, never only once at connection save - DNS can be re-pointed
    afterwards (the guard's own rebinding rationale). Callers:
    ``AutoCountProvider.validate_config`` (save time), this module's own
    ``probe_open_connection`` (the provider Test button AND open-company
    onboarding), and ``http_source.client.HttpApiClient.get`` (the paged
    walk, every lookup, and the preview sample all share that one
    request path). Raises ``OpenProbeError``, operator-safe, naming
    ``baseUrl``.

    Sprint-5/10 confirm-3 B1 (ruling): the scheme is UNRESTRICTED
    (``ALLOWED_BASE_URL_SCHEMES`` - both ``http`` and ``https``), the TARGET
    is restricted - unlike every other caller of the house guard, which
    stays https-only. A plain-http wrapper on a genuinely PUBLIC, resolvable
    host is allowed exactly like an https one; a private/loopback/
    link-local/reserved/metadata target is refused on EITHER scheme.
    """
    host = urlsplit(base_url or "").hostname or ""
    if settings.environment == "development" and _is_dev_local_host(host):
        return
    try:
        validate_public_url(
            base_url, allowed_schemes=ALLOWED_BASE_URL_SCHEMES, subject="baseUrl"
        )
    except UrlGuardError as exc:
        raise OpenProbeError(str(exc)) from exc


def probe_open_connection(
    base_url: str, *, transport: Optional[httpx.Client] = None
) -> List[Any]:
    """``GET {base_url}/location`` -> the parsed JSON array, or raise
    ``OpenProbeError``.

    ``transport``, when given, is a FULL ``httpx.Client`` (house convention -
    see ``client_from_connection``) used AS-IS, never wrapped again. A
    trailing slash on ``base_url`` is stripped exactly once so the built URL
    never double-slashes (AC-08-03).
    """
    assert_autocount_base_url_deliverable(base_url)
    url = f"{(base_url or '').rstrip('/')}/location"
    client = transport if transport is not None else httpx.Client(
        timeout=OPEN_PROBE_TIMEOUT_SECONDS,
        # S5 (sprint-5/08 review round 1) - never silently follow a redirect
        # to a host the operator never typed (SSRF-adjacent; the base URL is
        # the ONLY endpoint this probe is meant to reach).
        follow_redirects=False,
    )
    owns_client = transport is None
    try:
        try:
            response = client.get(
                url,
                headers={"Accept": "application/json"},
                timeout=OPEN_PROBE_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise OpenProbeError(
                f"Could not reach {base_url} - the request timed out "
                f"(reachability)."
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenProbeError(
                f"Could not reach {base_url} ({type(exc).__name__}) - check "
                f"the base URL (reachability)."
            ) from exc

        if not (200 <= response.status_code < 300):
            raise OpenProbeError(
                f"AutoCount answered HTTP {response.status_code} at "
                f"{url.rsplit('://', 1)[-1]}."
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise OpenProbeError(
                "AutoCount's response was not JSON."
            ) from exc
        if isinstance(body, list):
            return body
        # A dict carrying a paged envelope (``{Data: [...]}``) is ALSO
        # evidence of a genuine AutoCount open-API response - `/location`
        # itself always answers a bare array in production, but the probe's
        # job is "is this endpoint reachable and speaking our envelope",
        # not "is THIS specific endpoint's shape a bare array". Anything
        # else (not JSON-array-shaped, no ``Data`` list) is rejected.
        if isinstance(body, dict) and isinstance(body.get("Data"), list):
            return body["Data"]
        raise OpenProbeError(
            "AutoCount's response was not a JSON array."
        )
    finally:
        if owns_client:
            client.close()

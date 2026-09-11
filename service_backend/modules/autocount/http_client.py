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

import httpx

# 10s per AC-08-02 - a probe, not an extraction; a slow/hung wrapper must
# fail fast rather than hold up the Test button or the create form.
OPEN_PROBE_TIMEOUT_SECONDS = 10.0


class OpenProbeError(Exception):
    """The open-connection probe failed. ``message`` names the failing STEP
    (reachability / not JSON / an HTTP status) and is always operator-safe -
    never the raw response body (AC-08-02)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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
    url = f"{(base_url or '').rstrip('/')}/location"
    client = transport if transport is not None else httpx.Client(
        timeout=OPEN_PROBE_TIMEOUT_SECONDS
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

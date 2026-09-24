"""Generic CORS handler for MODULE-registered public prefixes (plan
sprint-4/34 review round 1, S9).

A **pure ASGI** middleware (never `BaseHTTPMiddleware`, which would add an
anyio task group to every request in the app - including the streaming
responses in `app/api/v1/imports.py` - to serve a handful of paths). The very
first thing it does is a string compare on `scope["path"]`; a non-matching
request is handed straight down with nothing wrapped and nothing allocated.

Two behaviours, both for registered prefixes only:

1. **It answers the browser's preflight.** The stock `CORSMiddleware` knows
   only this service's `CORS_ORIGINS` env, and a module's public prefix is
   allowlisted from TENANT data (e.g. a web chat channel's own
   `allowedOrigins`), so `CORSMiddleware` answers a legitimate customer site's
   `OPTIONS` with `400 Disallowed CORS origin` and the real POST is never
   sent. The registered resolver decides; an origin it refuses still gets a
   `204` (a preflight always does) but with NO `Access-Control-Allow-Origin`,
   so the browser blocks the real request. The echo is never `*`.

2. **It strips `Access-Control-Allow-Credentials`.** `CORSMiddleware` stamps
   that header onto every response whose request carries an `Origin`,
   unconditionally, before it checks whether the origin matches. These public
   surfaces carry no cookie by design (plan 34 D-A7B-4) and must never
   advertise credentialed CORS.

3. **It dedupes `Vary`.** These routes set their own `Vary: Origin` (the
   allowlist is per-CHANNEL tenant data - see `cors_headers_for`), and
   `CORSMiddleware` ALSO appends `Origin` to `Vary` on every response whose
   request carries an `Origin` header. Starlette < 1.7's `CORSMiddleware`
   used `MutableHeaders.add_vary_header`, which is idempotent, so the two
   collapsed into one `Origin` for free. Starlette 1.7 replaced that with a
   blind `", ".join([*headers.getlist("Vary"), "Origin"])` with no
   dedup, so the same combination now emits `Vary: Origin, Origin` - a
   starlette-version-dependent duplicate, not a bug in either header being
   set. Collapsing repeated tokens here keeps the response correct on any
   starlette version without either side needing to know about the other.

Ordering: `add_middleware` inserts at index 0 (LIFO), so this must be
registered AFTER `CORSMiddleware` in `app/main.py` to sit OUTSIDE it - which
is what lets it short-circuit the preflight and edit the credentials/vary
headers `CORSMiddleware` already added.
"""
import logging
from typing import Any, Dict, List, Tuple

from starlette.concurrency import run_in_threadpool

from app.module_platform.public_cors import match_public_cors_prefix

logger = logging.getLogger(__name__)

_PREFLIGHT_HEADERS: List[Tuple[bytes, bytes]] = [
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-allow-headers", b"authorization, content-type"),
    (b"access-control-max-age", b"600"),
    (b"vary", b"Origin"),
]


def _header(scope: Dict[str, Any], name: bytes) -> str:
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1")
    return ""


def _dedupe_vary(value: bytes) -> bytes:
    """Collapse repeated, comma-separated tokens in a `Vary` header value,
    case-insensitively, keeping the first-seen casing and order. `Origin,
    Origin` -> `Origin`; already-clean input is returned unchanged."""
    seen: List[str] = []
    seen_lower = set()
    for token in value.decode("latin-1").split(","):
        token = token.strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen_lower:
            continue
        seen_lower.add(lowered)
        seen.append(token)
    return ", ".join(seen).encode("latin-1")


class PublicCorsMiddleware:
    """Registry-driven; core holds no module path constants."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        entry = match_public_cors_prefix(scope.get("path") or "")
        if entry is None:
            await self.app(scope, receive, send)
            return

        origin = _header(scope, b"origin")
        if scope.get("method") == "OPTIONS" and _header(scope, b"access-control-request-method"):
            headers = list(_PREFLIGHT_HEADERS)
            if origin and await self._allows(entry, scope.get("path") or "", origin):
                headers.append((b"access-control-allow-origin", origin.encode("latin-1")))
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                kept: List[Tuple[bytes, bytes]] = []
                vary_values: List[bytes] = []
                vary_index = None
                for key, value in message.get("headers") or ():
                    if key.lower() == b"access-control-allow-credentials":
                        continue
                    if key.lower() == b"vary":
                        vary_values.append(value)
                        if vary_index is None:
                            vary_index = len(kept)
                        continue
                    kept.append((key, value))
                if vary_values:
                    merged = _dedupe_vary(b", ".join(vary_values))
                    kept.insert(vary_index, (b"vary", merged))
                message["headers"] = kept
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    async def _allows(entry, path: str, origin: str) -> bool:
        """Total by contract - a resolver that raises refuses, and says so in
        the log, rather than 500ing a preflight.

        B5 (review round 3): a resolver may run blocking I/O (a DB lookup on
        a cache miss - see `preflight_origin_allowed`), and `__call__` is a
        plain ASGI coroutine with nothing else dispatching it to a thread.
        Every other DB-touching route in this app is a sync `def` FastAPI
        route, which Starlette already runs in its threadpool for free; this
        is the one place that would otherwise run on the event loop, so it
        dispatches through the SAME threadpool explicitly. Without this, a
        distinct-key probe (no rate limit bounds it - B4) could hold the
        worker's event loop for a full connection-pool timeout once the pool
        is exhausted, stalling every other request the worker serves."""
        try:
            return bool(await run_in_threadpool(entry.resolver, path, origin))
        except Exception:  # noqa: BLE001 - a preflight must never 500
            logger.exception(
                "public CORS resolver for '%s' (%s) failed", entry.prefix, entry.provider_module
            )
            return False

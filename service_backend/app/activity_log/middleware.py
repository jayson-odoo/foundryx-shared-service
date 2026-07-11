"""Public-gateway request-logging middleware (sprint-4/12 Slice 1 + enhancement).

Scoped to the ``/api/v1/omnichannel`` path prefix (a cheap string check skips
every other request with zero overhead — the app is called directly). For each
gateway request it:
  1. mints a ``trace_id`` (uuid), stashes it on ``scope["state"]`` (so the
     downstream ``request.state`` sees it) + the contextvar (the outbound Meta
     call reads it);
  2. **tees** the request + response bodies WITHOUT consuming either stream — a
     wrapped ``receive`` copies inbound-body chunks and a wrapped ``send`` copies
     outbound-body chunks + the ``http.response.start`` status, passing every
     chunk through UNCHANGED so the handler + client are unaffected;
  3. records ONE ``inbound_api`` ``integration_activity`` row — attributed via
     the ``ApiWorkspace`` the gateway auth dep stashes on ``request.state``, with
     the redacted request/response bodies in the summaries.

This is a **pure ASGI middleware** (not ``BaseHTTPMiddleware``): only pure ASGI
can wrap ``receive``/``send`` to capture bodies without buffering-then-replaying
the whole stream (which ``BaseHTTPMiddleware`` forces and which breaks streaming
handlers). ``scope["state"]`` is a dict shared with the downstream ``Request``
(Starlette backs ``request.state`` with it), so the gateway dep's
``request.state.api_workspace`` write is visible to our post-response record.

Capture is SAFETY-CAPPED and SAFETY-TYPED:
  * JSON bodies only (``application/json``) are buffered + parsed; ``multipart/*``
    and any other/binary body is NEVER buffered — a small ``{"note": …}`` records
    its declared type + byte size instead (file uploads never bloat a log row);
  * a 16KB cap stops the copy early and marks ``{"truncated": true}`` — a
    pathological body can never blow up memory or the row;
  * everything captured is redacted through ``redact()`` (secret KEYS masked;
    message CONTENT preserved) by ``ActivityLogService.record``.

The write is failure-isolated on TWO levels: ``record`` swallows its own insert
error, AND the whole capture+record path is wrapped in ``_safe_record`` so
NOTHING here can propagate into — or mask the exception of — the observed
request. Eager mode (dev/E2E/tests) records inline on the request task
(deterministic, no cross-thread session race); prod records off the critical
path in a threadpool AFTER the full response is already sent (adds no client
latency, never blocks the event loop). A request with no resolvable workspace
(unauthenticated ``invalid_api_key`` 401) has no tenant to attribute → skipped.
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.activity_log.context import set_trace_id, trace_id_var
from app.activity_log.service import ActivityLogService
from app.config import settings
from app.database import SessionLocal, get_db
from app.models.integration_activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    SOURCE_INBOUND_API,
)

logger = logging.getLogger(__name__)

_GATEWAY_PREFIX = "/api/v1/omnichannel"
# Max bytes buffered per body — beyond this the copy stops + the summary marks
# {"truncated": true}. A body is NEVER buffered unbounded.
_BODY_CAP = 16 * 1024


def _open_session(request: Request):
    """A DB session for the log write. Honors a ``get_db`` dependency override
    (so tests write to their in-memory DB, not the real one) else the app's
    ``SessionLocal``. Returns ``(session, closer)``."""
    override = request.app.dependency_overrides.get(get_db)
    if override is not None:
        gen = override()
        session = next(gen)

        def _close() -> None:
            try:
                next(gen)
            except StopIteration:
                pass

        return session, _close
    db = SessionLocal()
    return db, db.close


def _scope_header(scope: Scope, name: bytes) -> Optional[str]:
    for k, v in scope.get("headers", []):
        if k.lower() == name:
            try:
                return v.decode("latin-1")
            except Exception:  # noqa: BLE001
                return None
    return None


def _is_json(content_type: Optional[str]) -> bool:
    return bool(content_type) and content_type.split(";", 1)[0].strip().lower() == "application/json"


def _summarize_body(
    raw: bytes, *, content_type: Optional[str], total_size: int, is_json: bool, truncated: bool
) -> Optional[Any]:
    """Turn a teed body into a JSON-storable, un-redacted summary value (the
    service redacts it). ``None`` when there is no body. A JSON body parses to its
    object; a truncated JSON body / unparseable body stores the capped raw string;
    a non-JSON (multipart/binary) body stores a size note ONLY — never the bytes."""
    if total_size <= 0:
        return None
    if not is_json:
        label = (content_type or "").split(";", 1)[0].strip() or "binary"
        return {"note": f"{label} body ({total_size} bytes) not captured"}
    text = raw.decode("utf-8", errors="replace")
    if truncated:
        return {"truncated": True, "raw": text}
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001 — malformed JSON: keep the capped raw text.
        return {"raw": text}


class _BodyTee:
    """Accumulates up to ``_BODY_CAP`` bytes of a body while tracking the true
    total size + whether the cap was hit. Only buffers when ``capture`` (JSON)."""

    def __init__(self, capture: bool):
        self.capture = capture
        self.buf = bytearray()
        self.total = 0
        self.truncated = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total += len(chunk)
        if not self.capture:
            return
        remaining = _BODY_CAP - len(self.buf)
        if remaining <= 0:
            self.truncated = True
            return
        if len(chunk) > remaining:
            self.buf.extend(chunk[:remaining])
            self.truncated = True
        else:
            self.buf.extend(chunk)


class GatewayActivityMiddleware:
    """Pure ASGI middleware — see the module docstring."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Fast path — skip everything that isn't an HTTP gateway request.
        if scope.get("type") != "http" or not scope.get("path", "").startswith(_GATEWAY_PREFIX):
            await self.app(scope, receive, send)
            return

        trace_id = str(uuid.uuid4())
        # scope["state"] is the dict Starlette backs request.state with — share it
        # so the downstream dep's request.state.api_workspace reaches our record.
        state = scope.setdefault("state", {})
        state["trace_id"] = trace_id
        token = set_trace_id(trace_id)

        occurred_at = datetime.now(timezone.utc)
        started = time.monotonic()

        req_ct = _scope_header(scope, b"content-type")
        req_tee = _BodyTee(capture=_is_json(req_ct))
        # Wrap receive: copy inbound-body chunks, pass every message through UNCHANGED.
        async def wrapped_receive() -> Message:
            message = await receive()
            if message.get("type") == "http.request":
                try:
                    req_tee.feed(message.get("body", b"") or b"")
                except Exception:  # noqa: BLE001 — capture must never break receive.
                    pass
            return message

        resp: dict[str, Any] = {"status": 500, "content_type": None}
        resp_tee_ref: dict[str, Optional[_BodyTee]] = {"tee": None}
        # Wrap send: capture status + JSON response-body chunks, pass through UNCHANGED.
        async def wrapped_send(message: Message) -> None:
            try:
                mtype = message.get("type")
                if mtype == "http.response.start":
                    resp["status"] = message.get("status", 500)
                    ct = None
                    for k, v in message.get("headers", []) or []:
                        if k.lower() == b"content-type":
                            ct = v.decode("latin-1")
                            break
                    resp["content_type"] = ct
                    resp_tee_ref["tee"] = _BodyTee(capture=_is_json(ct))
                elif mtype == "http.response.body":
                    tee = resp_tee_ref["tee"]
                    if tee is not None:
                        tee.feed(message.get("body", b"") or b"")
            except Exception:  # noqa: BLE001 — capture must never break send.
                pass
            await send(message)

        try:
            try:
                await self.app(scope, wrapped_receive, wrapped_send)
            except Exception as exc:  # noqa: BLE001 — record best-effort, re-raise unchanged.
                latency_ms = int((time.monotonic() - started) * 1000)
                err_args = (
                    scope, trace_id, 500, latency_ms,
                    f"{type(exc).__name__}: {exc}", occurred_at,
                    req_tee, req_ct, resp, resp_tee_ref["tee"],
                )
                # Mirror the happy path: inline in eager, else threadpool so the
                # sync DB write never blocks the event loop under a 500 storm.
                if settings.celery_task_always_eager:
                    self._safe_record(*err_args)
                else:
                    await run_in_threadpool(self._safe_record, *err_args)
                raise
            latency_ms = int((time.monotonic() - started) * 1000)
            args = (
                scope, trace_id, resp["status"], latency_ms, None, occurred_at,
                req_tee, req_ct, resp, resp_tee_ref["tee"],
            )
            # Eager mode: record inline on THIS task/session (deterministic, no
            # cross-thread session race — a BackgroundTask thread flaked the trace
            # test). Prod: the full response is already sent by the time self.app
            # returns, so run the sync DB write in a threadpool — zero client
            # latency, event loop never blocked.
            if settings.celery_task_always_eager:
                self._safe_record(*args)
            else:
                await run_in_threadpool(self._safe_record, *args)
        finally:
            trace_id_var.reset(token)

    @classmethod
    def _safe_record(
        cls,
        scope: Scope,
        trace_id: str,
        status_code: int,
        latency_ms: int,
        error_message: Optional[str],
        occurred_at: datetime,
        req_tee: _BodyTee,
        req_ct: Optional[str],
        resp: dict,
        resp_tee: Optional[_BodyTee],
    ) -> None:
        """Bare guard around ``_record`` — the logging path can NEVER propagate
        into or mask the observed request. Any failure is swallowed + logged."""
        try:
            cls._record(
                scope, trace_id, status_code, latency_ms, error_message,
                occurred_at, req_tee, req_ct, resp, resp_tee,
            )
        except Exception:  # noqa: BLE001 — logging must never break the request.
            logger.exception("integration_activity: failed to record gateway request")

    @staticmethod
    def _record(
        scope: Scope,
        trace_id: str,
        status_code: int,
        latency_ms: int,
        error_message: Optional[str],
        occurred_at: datetime,
        req_tee: _BodyTee,
        req_ct: Optional[str],
        resp: dict,
        resp_tee: Optional[_BodyTee],
    ) -> None:
        # A lightweight Request over the same scope reads state/headers/method/url
        # (no receive needed — the body is already teed, never re-read here).
        request = Request(scope)
        # Attribution: the gateway auth dep stashes the resolved ApiWorkspace on
        # request.state as soon as the key resolves (even a 403). None ⇒
        # unattributable → record() skips.
        ws = getattr(request.state, "api_workspace", None)
        tenant_id = getattr(ws, "tenant_id", None)
        if tenant_id is None:
            return

        path = request.url.path
        operation = f"{request.method} {path[len(_GATEWAY_PREFIX):] or '/'}"
        status = ACTIVITY_SUCCESS if status_code < 400 else ACTIVITY_ERROR

        req_summary = _request_summary(request, req_tee, req_ct)
        resp_summary = _response_summary(resp, resp_tee)

        db, close = _open_session(request)
        try:
            ActivityLogService(db).record(
                tenant_id=tenant_id,
                source=SOURCE_INBOUND_API,
                operation=operation,
                status=status,
                trace_id=trace_id,
                workspace_id=getattr(ws, "workspace_id", None),
                api_key_id=getattr(ws, "key_id", None),
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
                error_code=(str(status_code) if status_code >= 400 else None),
                error_message=error_message,
                occurred_at=occurred_at,
                request=req_summary,
                response=resp_summary,
            )
        finally:
            close()


def _request_summary(request: Request, tee: _BodyTee, content_type: Optional[str]) -> dict:
    """Metadata (headers redacted downstream) + the teed body (JSON parsed, or a
    size note for multipart/binary, or a truncation marker). The body is captured
    without consuming the stream (the handler already read the real bytes)."""
    summary: dict[str, Any] = {
        "path": request.url.path,
        "method": request.method,
        "query": dict(request.query_params),
        "headers": dict(request.headers),
    }
    body = _summarize_body(
        bytes(tee.buf),
        content_type=content_type,
        total_size=tee.total,
        is_json=tee.capture,
        truncated=tee.truncated,
    )
    if body is not None:
        summary["body"] = body
    return summary


def _response_summary(resp: dict, tee: Optional[_BodyTee]) -> Optional[dict]:
    """The redacted response body (JSON only) — replaces the old "No payload
    captured" for JSON responses. Non-JSON responses record no body."""
    if tee is None:
        return None
    body = _summarize_body(
        bytes(tee.buf),
        content_type=resp.get("content_type"),
        total_size=tee.total,
        is_json=tee.capture,
        truncated=tee.truncated,
    )
    if body is None:
        return None
    return {"statusCode": resp.get("status"), "body": body}

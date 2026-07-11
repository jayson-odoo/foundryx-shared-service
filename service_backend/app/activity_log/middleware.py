"""Public-gateway request-logging middleware (sprint-4/12 Slice 1, AC-DLC-03).

Scoped to the ``/api/v1/omnichannel`` path prefix (a cheap string check skips
every other request). For each gateway request it:
  1. mints a ``trace_id`` (uuid), stashes it on ``request.state`` + the
     contextvar (Slice 2's outbound Meta call reads it);
  2. times the request, capturing the final ``status_code`` even for handled
     ApiErrors (they become a Response before ``call_next`` returns) and 500s;
  3. records ONE ``inbound_api`` ``integration_activity`` row — attributed via
     the ``ApiWorkspace`` the gateway auth dep stashes on ``request.state``.

The write is failure-isolated on TWO levels: ``ActivityLogService.record``
swallows its own insert error, AND the whole ``_record`` call (session open,
summary build, close) is wrapped in ``_safe_record`` so NOTHING in the logging
path can propagate into — or mask the exception of — the observed request. On the
success/handled path the write runs as a Starlette ``BackgroundTask`` (executed
in a threadpool AFTER the response is sent), so it adds no latency and never
blocks the event loop; only the rare unhandled-500 path records inline (guarded)
before re-raising. A request with no resolvable workspace (unauthenticated
``invalid_api_key`` 401) has no tenant to attribute → it is skipped (documented
in the model).
"""
import logging
import time
import uuid
from typing import Optional

from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.activity_log.context import set_trace_id, trace_id_var
from app.activity_log.service import ActivityLogService
from app.database import SessionLocal, get_db
from app.models.integration_activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    SOURCE_INBOUND_API,
)

logger = logging.getLogger(__name__)

_GATEWAY_PREFIX = "/api/v1/omnichannel"


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


class GatewayActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Fast prefix check — skip everything that isn't the public gateway.
        if not request.url.path.startswith(_GATEWAY_PREFIX):
            return await call_next(request)

        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        token = set_trace_id(trace_id)

        started = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001 — record best-effort, re-raise unchanged.
                latency_ms = int((time.monotonic() - started) * 1000)
                self._safe_record(
                    request, trace_id, 500, latency_ms, f"{type(exc).__name__}: {exc}"
                )
                raise
            # Handled/success path — record OFF the response critical path so the
            # write never adds latency or blocks the loop. A sync BackgroundTask
            # runs in a threadpool after the response is sent.
            latency_ms = int((time.monotonic() - started) * 1000)
            task = BackgroundTask(
                self._safe_record, request, trace_id, response.status_code, latency_ms, None
            )
            if response.background is None:
                response.background = task
            else:  # a handler already set a background task — record inline (guarded).
                self._safe_record(request, trace_id, response.status_code, latency_ms, None)
            return response
        finally:
            trace_id_var.reset(token)

    @classmethod
    def _safe_record(
        cls,
        request: Request,
        trace_id: str,
        status_code: int,
        latency_ms: int,
        error_message: Optional[str],
    ) -> None:
        """Bare guard around ``_record`` — the logging path (session open, summary
        build, insert, close) can NEVER propagate into or mask the observed
        request. Any failure is swallowed + logged."""
        try:
            cls._record(request, trace_id, status_code, latency_ms, error_message)
        except Exception:  # noqa: BLE001 — logging must never break the request.
            logger.exception("integration_activity: failed to record gateway request")

    @staticmethod
    def _record(
        request: Request,
        trace_id: str,
        status_code: int,
        latency_ms: int,
        error_message: Optional[str],
    ) -> None:
        # Attribution: the gateway auth dep stashes the resolved ApiWorkspace on
        # request.state (set as soon as the key resolves — even a 403
        # service_not_enabled carries it). None ⇒ unattributable → record()
        # skips.
        ws = getattr(request.state, "api_workspace", None)
        tenant_id = getattr(ws, "tenant_id", None)
        if tenant_id is None:
            return

        path = request.url.path
        operation = f"{request.method} {path[len(_GATEWAY_PREFIX):] or '/'}"
        status = ACTIVITY_SUCCESS if status_code < 400 else ACTIVITY_ERROR

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
                request=_request_summary(request),
            )
        finally:
            close()


def _request_summary(request: Request) -> dict:
    """Metadata-only summary (headers redacted downstream). The body is not read
    here — re-reading a consumed stream in middleware risks breaking the handler;
    per-operation body capture is a later refinement."""
    return {
        "path": request.url.path,
        "method": request.method,
        "query": dict(request.query_params),
        "headers": dict(request.headers),
    }

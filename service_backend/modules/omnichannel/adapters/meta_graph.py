"""Shared Meta Graph API plumbing (plan 32 / A7a, D-A7-1/D-A7-9).

Extracted verbatim out of ``whatsapp_cloud.py`` so the Messenger and Instagram
adapters share the SAME telemetry wrapper, the SAME dev-safe/"configured" rule
and the SAME base-URL/HTTP-client plumbing as WhatsApp - all three are
products of ONE Meta app (``META_APP_ID``/``META_APP_SECRET``/
``META_GRAPH_VERSION``), never three separate integrations.

``whatsapp_cloud.py`` re-imports every name here (``GraphCall``,
``GraphRecorder``, ``_meta_error_detail``, ``MetaGraphMixin``) so its own
observable behaviour - and every existing import site (``services/activity.py``
imports ``GraphCall``/``GraphRecorder`` straight off ``whatsapp_cloud``) - is
byte-identical to before this move (AC-CHN-15, F8: if this stopped being a
pure move the slice should have stopped and re-planned).
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from app.config import settings
from .base import SendError

logger = logging.getLogger(__name__)


@dataclass
class GraphCall:
    """Telemetry for ONE outbound Meta/Graph call - what an adapter reports to
    an (optional) recorder so the Developers -> Logs console gets an
    ``outbound_meta`` row (sprint-4/12 Slice 2, AC-DLC-14). The adapter stays
    free of any DB knowledge: it only describes the call; the recorder (owned by
    the service layer) persists it, attributing tenant + reading the inbound
    trace id off the contextvar."""

    operation: str  # graph:send | graph:template_submit | graph:sync
    status: str  # "success" | "error"
    status_code: Optional[int]
    latency_ms: int
    error_code: Optional[str]
    error_message: Optional[str]
    external_ref: Optional[str]  # wamid / message_id on a successful send


# A recorder is a failure-isolated sink; it must never raise back into the send.
GraphRecorder = Callable[[GraphCall], None]


# Meta throttling/rate-limit error codes (plan 32 S5, AC-CHN-51). Meta does
# NOT reserve a 5xx status for these - a page or app quota breach still comes
# back as HTTP 400 (sometimes 200) with one of these `error.code` values, or
# occasionally a bare HTTP 429. Only Messenger/Instagram call
# `is_rate_limited_error` (`adapters/messenger.py`) - WhatsApp's own transient
# rule (`status_code >= 500`) stays byte-identical (AC-CHN-23).
# Source (error codes 4 "API Too Many Calls", 17 "User request limit
# reached", 32 "Page request limit reached", 613 "Calls to this api have
# exceeded the rate limit"; the per-call `X-Business-Use-Case-Usage` header):
# https://developers.facebook.com/docs/graph-api/guides/error-handling
# https://developers.facebook.com/docs/graph-api/overview/rate-limiting
_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}


def is_rate_limited_error(resp: "httpx.Response") -> bool:
    """True when this Graph response is Meta throttling the call - a raw HTTP
    429, or an `error.code` in `_RATE_LIMIT_ERROR_CODES` regardless of HTTP
    status. Never raises - a malformed/non-JSON error body is simply "not a
    rate limit" (the caller's normal error path still fires)."""
    if resp.status_code == 429:
        return True
    try:
        code = ((resp.json() or {}).get("error") or {}).get("code")
    except ValueError:
        return False
    return code in _RATE_LIMIT_ERROR_CODES


def _meta_error_detail(resp: "httpx.Response") -> str:
    """Assemble the most specific message Meta gives. ``error.message`` alone is
    often the generic title ("Invalid parameter"); the real reason lives in
    ``error_user_title``/``error_user_msg`` and ``error_data.details``. Surface
    all of them so the operator sees WHY a template was rejected."""
    try:
        err = (resp.json() or {}).get("error", {}) or {}
    except ValueError:
        return f"Meta returned {resp.status_code}."
    parts = []
    for key in ("error_user_title", "error_user_msg"):
        val = (err.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    details = ((err.get("error_data") or {}).get("details") or "").strip()
    if details and details not in parts:
        parts.append(details)
    if not parts:
        msg = (err.get("message") or "").strip()
        parts.append(msg or f"Meta returned {resp.status_code}.")
    return " - ".join(parts)


class MetaGraphMixin:
    """Shared Graph-call plumbing every Meta-app-backed adapter (WhatsApp,
    Messenger, Instagram) mixes in: ``_configured``/dev-safe gate, an
    ``httpx`` client factory, the ``{base}`` Graph URL, and the timed +
    recorded ``_graph_call`` wrapper. Concrete adapters own everything
    provider-specific (payload shape, endpoint paths, ``parse_inbound``)."""

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        recorder: Optional[GraphRecorder] = None,
    ):
        self._client = client
        self._recorder = recorder
        # Last Meta HTTP status seen inside a wrapped call (one logical exchange
        # per ``_graph_call``) so the recorder can stamp the real status code on
        # BOTH success and error rows. Reset per call.
        self._last_http_status: Optional[int] = None
        self._base = f"https://graph.facebook.com/{settings.meta_graph_version}"

    def _graph_call(
        self,
        operation: str,
        fn: Callable[[], Any],
        *,
        extract_ref: Optional[Callable[[Any], Optional[str]]] = None,
    ) -> Any:
        """Time + record ONE Graph call (AC-DLC-14). With no recorder this is a
        transparent pass-through (existing behaviour, tests unaffected). The
        record is fully failure-isolated - a logging failure can NEVER break the
        send."""
        if self._recorder is None:
            return fn()
        self._last_http_status = None
        started = time.monotonic()
        status = "success"
        error_code: Optional[str] = None
        error_message: Optional[str] = None
        external_ref: Optional[str] = None
        try:
            result = fn()
            if extract_ref is not None:
                external_ref = extract_ref(result)
            return result
        except SendError as exc:
            status = "error"
            error_code = "SendError"
            error_message = str(exc)
            raise
        except Exception as exc:  # noqa: BLE001 - report + re-raise unchanged.
            status = "error"
            error_code = type(exc).__name__
            error_message = str(exc)
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            try:
                self._recorder(
                    GraphCall(
                        operation=operation,
                        status=status,
                        status_code=self._last_http_status,
                        latency_ms=latency_ms,
                        error_code=error_code,
                        error_message=error_message,
                        external_ref=external_ref,
                    )
                )
            except Exception:  # noqa: BLE001 - recording must never break the send.
                logger.exception("outbound-meta activity record failed (%s)", operation)

    @property
    def _configured(self) -> bool:
        return bool(settings.meta_app_id and settings.meta_app_secret)

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=10.0)

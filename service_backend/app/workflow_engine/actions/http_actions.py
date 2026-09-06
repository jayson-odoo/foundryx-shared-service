"""``http.request`` - the generic outbound-HTTP core action (plan sprint-4/31
S5, AC-WFP-57..62). Gated by the CORE permission ``workflows.http``
(``ActionDef.permission``, mirrors ``workflows.code``'s gate on
``code.run``): an API-key-free, tenant-authored outbound HTTP call is the
same blast radius as a Code node (D-A5-12).

Security invariants:
- https-only, re-checked via ``app/services/url_guard.py`` IMMEDIATELY
  BEFORE every request (never trust publish-time validation alone - a URL
  that looked public at save can resolve internally by the time the node
  actually runs).
- Redirects are DISABLED on the client (``follow_redirects=False``) - a 3xx
  to an internal address would otherwise bypass the pre-flight-only guard.
- The response read is capped (``MAX_RESPONSE_BYTES``) so a hostile/huge body
  can never be buffered in full; a non-text response records size + content
  type only, never bytes.
- Header VALUES are merge-rendered here at execution time but the field is
  NOT declared ``mergeable`` on the ``ActionDef`` - the generic
  ``executor._node_input_json`` trace helper only renders fields flagged
  ``mergeable``, so header values are never written to the run trace (names
  only, via the raw ``config`` it always stores). This is enforced by
  ``tests/test_http_workflow_action.py``, not by any special case here.
"""
from __future__ import annotations

import json as json_module
import time
from typing import Any, Dict, List, Tuple

import httpx
from sqlalchemy.orm import Session

from app.services.url_guard import UrlGuardError, assert_deliverable
from app.workflow_engine.context import render_field


class ActionError(Exception):
    pass


METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
BODY_MODES = ("none", "json", "text")
DEFAULT_TIMEOUT_SECONDS = 10
MAX_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 256 * 1024  # AC-WFP-57/59 response-read cap
MAX_JSON_FLATTEN_KEYS = 500  # safety valve - never explode an enormous body


def _timeout_seconds(config: Dict[str, Any]) -> int:
    raw = config.get("timeoutSeconds")
    try:
        value = int(str(raw)) if raw not in (None, "") else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        value = DEFAULT_TIMEOUT_SECONDS
    return min(value, MAX_TIMEOUT_SECONDS)


def _headers(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, str]:
    """Merge-render each header VALUE (never traced - see module docstring).
    Blank keys are dropped; a later duplicate key wins (author order)."""
    rows = config.get("headers")
    out: Dict[str, str] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        out[key] = render_field(row.get("value"), ctx)
    return out


def _is_text_content_type(content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct:
        return False
    if ct.startswith("text/"):
        return True
    if ct in (
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-www-form-urlencoded",
    ):
        return True
    return ct.endswith("+json") or ct.endswith("+xml")


def _flatten_json(value: Any, prefix: str, out: Dict[str, Any], budget: List[int]) -> None:
    """Flatten a parsed JSON value into ``prefix.<dotted path>`` keys so the
    node output's flat-dotted contract (``nodes.<id>.json.<path>``) resolves
    through the SAME substitution-only merge renderer every other output
    already uses (no nested-object traversal support anywhere else in the
    engine - see ``app/template_engine/merge.py``). Capped so an enormous
    response body can never explode the run's output/trace row."""
    if budget[0] <= 0:
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            if budget[0] <= 0:
                return
            _flatten_json(sub, f"{prefix}.{key}", out, budget)
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            if budget[0] <= 0:
                return
            _flatten_json(sub, f"{prefix}.{index}", out, budget)
    else:
        out[prefix] = value
        budget[0] -= 1


def _body_and_content_type(
    config: Dict[str, Any], ctx: Dict[str, Any]
) -> Tuple[bytes, str]:
    """Merge-render the body per ``bodyMode``. AC-WFP-62: a ``json`` body mode
    must parse as JSON post-render, or the node fails BEFORE sending anything."""
    mode = str(config.get("bodyMode") or "none")
    if mode not in BODY_MODES:
        mode = "none"
    if mode == "none":
        return b"", ""
    rendered = render_field(config.get("body"), ctx)
    if mode == "json":
        if not rendered.strip():
            raise ActionError("The request body is not valid JSON after merging.")
        try:
            json_module.loads(rendered)
        except (ValueError, TypeError) as exc:
            raise ActionError(
                "The request body is not valid JSON after merging."
            ) from exc
        return rendered.encode("utf-8"), "application/json"
    return rendered.encode("utf-8"), "text/plain; charset=utf-8"


def http_request(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    method = str(config.get("method") or "").strip().upper()
    if method not in METHODS:
        raise ActionError("Method is not configured.")
    url = render_field(config.get("url"), ctx).strip()
    if not url:
        raise ActionError("URL is empty after merging.")
    try:
        assert_deliverable(url)
    except UrlGuardError as exc:
        # AC-WFP-58: uniform refusal message, no request ever sent.
        raise ActionError(f"URL refused: {exc}") from exc

    headers = _headers(config, ctx)
    body, default_content_type = _body_and_content_type(config, ctx)
    if default_content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = default_content_type

    timeout = _timeout_seconds(config)
    started = time.monotonic()
    try:
        # Module-level `httpx.stream` (not a `Client` instance) so a test can
        # monkeypatch `http_actions.httpx.stream` directly - the same
        # monkeypatch shape the pre-existing webhook-delivery tests already
        # use for `httpx.post`. `follow_redirects=False` is explicit (never
        # inherited from a default that could change) - a 302 to an internal
        # address must never be auto-followed past the pre-flight guard.
        with httpx.stream(
            method, url, headers=headers, content=body or None,
            timeout=timeout, follow_redirects=False,
        ) as resp:
            status_code = resp.status_code
            content_type = resp.headers.get("content-type", "")
            is_text = _is_text_content_type(content_type)
            chunks: List[bytes] = []
            total = 0
            truncated = False
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    truncated = True
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
    except httpx.HTTPError as exc:
        # AC-WFP-60: a transport error fails the node with its error class in
        # the message - no silent success.
        raise ActionError(f"Request failed: {type(exc).__name__}: {exc}") from exc
    duration_ms = int((time.monotonic() - started) * 1000)

    ok = 200 <= status_code < 300
    output: Dict[str, Any] = {
        "statusCode": status_code,
        "ok": ok,
        "durationMs": duration_ms,
    }
    if is_text:
        text_body = raw.decode("utf-8", errors="replace")
        output["body"] = text_body + (" (truncated)" if truncated else "")
        if not truncated:
            # A truncated body is incomplete by definition - never attempt to
            # parse it as JSON (a false "successful" parse of a cut-off
            # document would be worse than no parse at all).
            try:
                parsed = json_module.loads(text_body) if text_body.strip() else None
            except (ValueError, TypeError):
                parsed = None
            if parsed is not None:
                output["json"] = json_module.dumps(parsed, separators=(",", ":"))
                flat: Dict[str, Any] = {}
                _flatten_json(parsed, "json", flat, [MAX_JSON_FLATTEN_KEYS])
                output.update(flat)
    else:
        # AC-WFP-59: a non-text response records size + content type only -
        # never the raw bytes.
        output["body"] = f"[{content_type or 'binary'}, {total} bytes]"

    if not ok:
        # AC-WFP-60: a non-2xx response fails the node (with the status code
        # in the message) - the run FAILS and downstream nodes skip.
        raise ActionError(f"Request returned status {status_code}.")
    return output

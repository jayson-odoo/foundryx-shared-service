"""Trace/span writer (AC-BI-09) + payload caps (AC-BI-10).

Field naming follows **OTel GenAI semconv** (`gen_ai.system` → `provider`,
`gen_ai.request.model` → `model`, `gen_ai.usage.input_tokens` → `tokens_in`, …)
so a future OTLP export is a field-map, not a rewrite.

**Payload caps are not optional.** Prompts and completions are stored alongside
the transcript, which already duplicates the content; without a cap one long
grill bloats Postgres unbounded. Every string that lands in `input_json` /
`output_json` is truncated and the truncation is MARKED, so a reader can always
tell a short payload from a clipped one.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.ai import (
    SPAN_KIND_LLM_CALL,
    TRACE_STATUS_ERROR,
    TRACE_STATUS_OK,
    AiSpan,
    AiTrace,
)

# Per-string cap inside a span payload. Generous enough to keep a real prompt
# readable, small enough that 1000 traces stay a few MB.
MAX_PAYLOAD_CHARS = 8_000
# Total serialized cap for one payload object — the backstop when a payload has
# many individually-short values.
MAX_PAYLOAD_TOTAL_CHARS = 32_000
TRUNCATION_SUFFIX = "…[truncated]"
# Marker key added to a payload that lost content, so truncation is never silent.
TRUNCATED_FLAG = "_truncated"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cap_payload(payload: Optional[Any]) -> Optional[Any]:
    """Truncate strings inside a payload, MARKING that it happened.

    Returns a NEW structure — never mutates the caller's dict (the SQLAlchemy
    in-place-JSON-mutation trap).
    """
    if payload is None:
        return None

    truncated = False

    def walk(value: Any) -> Any:
        nonlocal truncated
        if isinstance(value, str):
            if len(value) > MAX_PAYLOAD_CHARS:
                truncated = True
                return value[:MAX_PAYLOAD_CHARS] + TRUNCATION_SUFFIX
            return value
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    capped = walk(payload)

    # Backstop: many short values can still add up. Drop to a marker rather
    # than storing an unbounded blob.
    try:
        serialized = json.dumps(capped, default=str)
    except (TypeError, ValueError):
        serialized = str(capped)
    if len(serialized) > MAX_PAYLOAD_TOTAL_CHARS:
        return {
            TRUNCATED_FLAG: True,
            "preview": serialized[:MAX_PAYLOAD_TOTAL_CHARS] + TRUNCATION_SUFFIX,
        }

    if truncated and isinstance(capped, dict):
        return {**capped, TRUNCATED_FLAG: True}
    return capped


class TraceWriter:
    """Accumulates spans for one run, then flushes trace + spans together.

    Nothing is written until `finish()` — a run that raises mid-way still lands
    exactly one trace row (with `status='error'`) plus the spans it got through,
    never a half-written trace the UI can't render.
    """

    def __init__(
        self,
        db: Session,
        *,
        tenant_id: str,
        agent_id: Optional[str] = None,
        agent_name: str = "",
        conversation_id: Optional[str] = None,
        skill_key: Optional[str] = None,
        prompt_version: Optional[int] = None,
        provider: str = "",
        model: str = "",
        created_by: Optional[str] = None,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.conversation_id = conversation_id
        self.skill_key = skill_key
        self.prompt_version = prompt_version
        self.provider = provider
        self.model = model
        self.created_by = created_by
        self._spans: List[AiSpan] = []
        self._started = _now()

    def add_span(
        self,
        *,
        span_kind: str,
        name: str = "",
        input_json: Optional[Any] = None,
        output_json: Optional[Any] = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        status: str = TRACE_STATUS_OK,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        parent_id: Optional[str] = None,
    ) -> AiSpan:
        span = AiSpan(
            tenant_id=self.tenant_id,
            parent_id=parent_id,
            # Slice 1 is a flat sequence; the dotted path is already the sort key
            # the tree renderer will use unchanged (Bi-D17).
            dotted_order=str(len(self._spans) + 1),
            span_kind=span_kind,
            name=name or span_kind,
            input_json=cap_payload(input_json),
            output_json=cap_payload(output_json),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            status=status,
            error=error,
            started_at=started_at or _now(),
        )
        self._spans.append(span)
        return span

    def finish(
        self, *, status: str = TRACE_STATUS_OK, error: Optional[str] = None
    ) -> AiTrace:
        """Write the trace + its spans. Caller owns the commit."""
        elapsed_ms = int((_now() - self._started).total_seconds() * 1000)
        trace = AiTrace(
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            skill_key=self.skill_key,
            prompt_version=self.prompt_version,
            provider=self.provider,
            model=self.model,
            # Roll up usage from the LLM spans — the trace total is what cost
            # tracking reads, so it must never drift from the spans.
            tokens_in=sum(s.tokens_in for s in self._spans),
            tokens_out=sum(s.tokens_out for s in self._spans),
            latency_ms=elapsed_ms,
            status=status,
            error=error,
            span_count=len(self._spans),
            created_by=self.created_by,
        )
        self.db.add(trace)
        self.db.flush()  # mint trace.id before the spans reference it
        for span in self._spans:
            span.trace_id = trace.id
            self.db.add(span)
        self.db.flush()
        return trace


def append_span(
    db: Session,
    trace: AiTrace,
    *,
    span_kind: str,
    name: str = "",
    input_json: Optional[Any] = None,
    output_json: Optional[Any] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    status: str = TRACE_STATUS_OK,
    error: Optional[str] = None,
) -> AiSpan:
    """Append ONE step to an already-written trace (the grill's ``validate`` /
    ``retry`` spans, AC-BI-25).

    ``AiClient.complete`` owns the ``llm_call`` span; the grill engine adds the
    validate/retry steps around it onto the SAME trace so the flat step list is
    the full run. Flush only — the caller owns the commit (the grill runs the
    whole turn/extract in one transaction). ``span_count`` is bumped so the trace
    total never drifts from its spans.
    """
    order = str((trace.span_count or 0) + 1)
    span = AiSpan(
        tenant_id=trace.tenant_id,
        trace_id=trace.id,
        parent_id=None,
        dotted_order=order,
        span_kind=span_kind,
        name=name or span_kind,
        input_json=cap_payload(input_json),
        output_json=cap_payload(output_json),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        status=status,
        error=error,
        started_at=_now(),
    )
    db.add(span)
    trace.span_count = (trace.span_count or 0) + 1
    db.flush()
    return span


def llm_span_payload(
    *, system: str, messages: List[Dict[str, str]], output_schema: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """The standard `llm_call` span input shape."""
    return {
        "system": system,
        "messages": messages,
        "structured": output_schema is not None,
    }


__all__ = [
    "TraceWriter",
    "append_span",
    "cap_payload",
    "llm_span_payload",
    "MAX_PAYLOAD_CHARS",
    "MAX_PAYLOAD_TOTAL_CHARS",
    "TRUNCATED_FLAG",
    "SPAN_KIND_LLM_CALL",
    "TRACE_STATUS_OK",
    "TRACE_STATUS_ERROR",
]

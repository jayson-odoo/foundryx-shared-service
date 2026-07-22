"""The generic grill engine (Bi-D7, AC-BI-20) — CORE, one layer up from Phase A's
``IntakeDefinition``.

A ``GrillDefinition`` binds *source artifact type + target template resolver +
skill + agent resolver + completion rule*. **Idea → BR is instance one**; adding
BR → FR later is a NEW definition row + template, not new engine code — the
target template's field list is injected into the prompt at runtime (AC-BI-08),
so ONE ``grill-me-business`` skill serves every target.

The engine runs two operations:

- **turn** — ONE structured LLM call returning ``{replyText, coveredFields[]}``
  (AC-BI-24b): the prose reply and the cheap coverage map come back together.
  ``coveredFields`` are answer-keys the transcript has grounded so far.
- **generate** — a SEPARATE extraction call over the WHOLE transcript + source
  artifacts (AC-BI-24), provider-native structured output shaped by the target
  fields, ``form_engine``-validated (type/format/choice ONLY, NOT ``required`` —
  AC-BI-26 partial emit), ONE retry with the errors fed back (AC-BI-25), then the
  cleaned answers are persisted via the definition's callback. **The model never
  writes** (AC-BI-27/D22-A): the agent holds no tool with a side effect; OUR code
  validates and persists, and the extraction NEVER promotes.

**Trace-on-error is load-bearing (decision 1 / AC-BI-24b).** ``AiClient.complete``
flushes its trace but the caller owns the commit, and ``get_db`` rolls back on any
uncaught exception. So EVERY completion here is wrapped: ``except LLMError`` →
``db.commit()`` (persist the flushed trace + spans) → then a clean error is
surfaced. A failed grill MUST leave an ``error`` trace behind (AC-BI-09).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.client import AiClient
from app.ai.prompt import compose, field_schema
from app.ai.tracing import append_span
from app.form_engine.validation import validate_submission
from app.integrations.base import LLMError, LLMResult
from app.models.ai import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SPAN_KIND_RETRY,
    SPAN_KIND_VALIDATE,
    TRACE_STATUS_ERROR,
    TRACE_STATUS_OK,
    AiAgent,
)
from app.repositories.ai_repository import ConversationRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(since: datetime) -> int:
    return int((_now() - since).total_seconds() * 1000)


class GrillError(Exception):
    """A clean, user-facing grill failure — the router maps it to an HTTP error.

    Distinct from ``LLMError`` (provider transport): the engine catches
    ``LLMError``, commits the error trace, then raises THIS so the trace survives
    the request teardown (decision 1).
    """


# ── the injected context for one target ──────────────────────────────────────


@dataclass
class GrillContext:
    """Everything the engine needs to grill ONE target, resolved by the
    definition. Keeping this data-shaped is what lets a second GrillDefinition
    (BR → FR) reuse the engine with only a new resolver."""

    tenant_id: str
    target_id: str
    # [{key, label}] — the target template's answer-keys, injected into the
    # prompt AND used to shape both output schemas.
    target_fields: List[Dict[str, str]]
    # The FormDocument (dict) the extraction validates against.
    target_doc: Dict[str, Any]
    # The linked source artifacts as plain text (grounding), e.g. idea bodies.
    source_artifacts: List[str]
    source_type: str
    source_ids: List[str]
    template_version: Optional[int]
    agent: AiAgent
    # The equipped skill body (already resolved to its active version) + the
    # version int, stamped onto the conversation + trace for attributability.
    skill_body: str
    skill_key: str
    prompt_version: Optional[int]


# resolve_context(db, tenant_id, target_id) -> GrillContext (raises GrillError)
ResolveContext = Callable[[Session, str, str], GrillContext]
# persist_answers(db, tenant_id, target_id, answers, actor) -> None. FLUSH-ONLY —
# the engine owns the commit; the callback NEVER promotes (writes answers only).
PersistAnswers = Callable[..., None]


@dataclass(frozen=True)
class GrillDefinition:
    """The generic binding (AC-BI-20). One row per source→target pairing."""

    key: str
    source_type: str
    skill_key: str
    resolve_context: ResolveContext
    persist_answers: PersistAnswers


_REGISTRY: Dict[str, GrillDefinition] = {}


def register_grill_definition(definition: GrillDefinition) -> None:
    """Register (idempotently) a grill definition by key — boot hooks re-run."""
    _REGISTRY[definition.key] = definition


def get_grill_definition(key: str) -> Optional[GrillDefinition]:
    return _REGISTRY.get(key)


# ── results ───────────────────────────────────────────────────────────────────


@dataclass
class TurnResult:
    reply_text: str
    covered_fields: List[str]


@dataclass
class GenerateResult:
    ok: bool
    answers: Dict[str, Any]
    field_errors: Dict[str, str]


@dataclass
class GrillState:
    """The transcript + coverage snapshot the Grill tab renders (AC-BI-29)."""

    fields: List[Dict[str, str]]
    messages: List[Dict[str, Any]]
    covered_fields: List[str]


# ── the engine ────────────────────────────────────────────────────────────────


class GrillEngine:
    def __init__(self, db: Session):
        self.db = db
        self.convos = ConversationRepository(db)

    # -- transcript read (no create) ------------------------------------------
    def state(
        self, definition: GrillDefinition, tenant_id: str, target_id: str
    ) -> GrillState:
        """The current transcript + coverage for the Grill tab. Read-only — never
        creates the conversation (a GET must not mutate; the first TURN creates
        it). ``covered_fields`` = the LATEST assistant turn's map."""
        ctx = definition.resolve_context(self.db, tenant_id, target_id)
        convo = self.convos.get_for_target(
            tenant_id,
            target_type=_target_type(definition),
            target_id=target_id,
            grill_definition_key=definition.key,
        )
        messages: List[Dict[str, Any]] = []
        covered: List[str] = []
        valid_keys = _valid_keys(ctx)
        if convo is not None:
            for m in self.convos.messages(convo.id):
                covered_fields = _clean_covered(m.covered_fields_json, valid_keys)
                messages.append(
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content or "",
                        "coveredFields": covered_fields,
                        "createdAt": m.created_at,
                    }
                )
                if m.role == ROLE_ASSISTANT:
                    covered = covered_fields
        return GrillState(fields=ctx.target_fields, messages=messages, covered_fields=covered)

    # -- one turn --------------------------------------------------------------
    def turn(
        self,
        definition: GrillDefinition,
        tenant_id: str,
        target_id: str,
        message: str,
        actor,
    ) -> TurnResult:
        ctx = definition.resolve_context(self.db, tenant_id, target_id)
        convo = self.convos.get_or_create_for_target(
            tenant_id,
            target_type=_target_type(definition),
            target_id=target_id,
            grill_definition_key=definition.key,
            source_type=ctx.source_type,
            source_ids=ctx.source_ids,
            prompt_version=ctx.prompt_version,
            template_version=ctx.template_version,
        )
        prior = self.convos.messages(convo.id)
        # Build the history IN MEMORY (the new user turn is not persisted yet) so
        # a provider failure leaves NO half-written turn (AC-BI-23): on error only
        # the error trace commits, never a user message with no reply.
        history = [{"role": m.role, "content": m.content or ""} for m in prior]
        history.append({"role": ROLE_USER, "content": message})

        system = _compose_system(ctx)
        schema = _turn_schema(ctx)
        result = self._complete(
            ctx,
            conversation_id=convo.id,
            system=system,
            messages=history,
            output_schema=schema,
            actor=actor,
        )

        valid_keys = _valid_keys(ctx)
        reply_text, covered = _parse_turn(result, valid_keys)
        # Persist BOTH turns atomically only after a successful completion.
        self.convos.add_message(
            conversation_id=convo.id,
            tenant_id=tenant_id,
            role=ROLE_USER,
            content=message,
        )
        self.convos.add_message(
            conversation_id=convo.id,
            tenant_id=tenant_id,
            role=ROLE_ASSISTANT,
            content=reply_text,
            covered_fields=covered,
        )
        self.db.commit()
        return TurnResult(reply_text=reply_text, covered_fields=covered)

    # -- generate (extraction) -------------------------------------------------
    def generate(
        self, definition: GrillDefinition, tenant_id: str, target_id: str, actor
    ) -> GenerateResult:
        """Extraction over the WHOLE transcript (AC-BI-24). Validates type/format
        ONLY (partial emit is success, AC-BI-26), one retry on validation failure
        (AC-BI-25), then persists the cleaned answers — the BR STAYS draft
        (AC-BI-27). One commit at the end; an LLM failure commits its trace first."""
        ctx = definition.resolve_context(self.db, tenant_id, target_id)
        convo = self.convos.get_or_create_for_target(
            tenant_id,
            target_type=_target_type(definition),
            target_id=target_id,
            grill_definition_key=definition.key,
            source_type=ctx.source_type,
            source_ids=ctx.source_ids,
            prompt_version=ctx.prompt_version,
            template_version=ctx.template_version,
        )
        transcript = self.convos.messages(convo.id)

        system = _compose_extraction_system(ctx)
        base_messages = _extraction_messages(ctx, transcript)
        schema = field_schema(ctx.target_fields)

        # Attempt 1.
        result, trace = self._complete_traced(
            ctx,
            conversation_id=convo.id,
            system=system,
            messages=base_messages,
            output_schema=schema,
            actor=actor,
        )
        structured = _structured(result)
        started = _now()
        clean, errors = validate_submission(ctx.target_doc, structured, enforce_required=False)
        append_span(
            self.db,
            trace,
            span_kind=SPAN_KIND_VALIDATE,
            name="validate",
            input_json={"answers": structured},
            output_json={"clean": clean, "errors": errors},
            latency_ms=_elapsed_ms(started),
            status=TRACE_STATUS_OK if not errors else TRACE_STATUS_ERROR,
            error=None if not errors else json.dumps(errors),
        )

        if errors:
            # Exactly ONE retry with the validation errors fed back (AC-BI-25).
            append_span(
                self.db,
                trace,
                span_kind=SPAN_KIND_RETRY,
                name="retry",
                input_json={"fieldErrors": errors},
            )
            retry_messages = base_messages + [
                {
                    "role": ROLE_USER,
                    "content": _retry_instruction(errors),
                }
            ]
            result2, trace2 = self._complete_traced(
                ctx,
                conversation_id=convo.id,
                system=system,
                messages=retry_messages,
                output_schema=schema,
                actor=actor,
            )
            structured = _structured(result2)
            started = _now()
            clean, errors = validate_submission(
                ctx.target_doc, structured, enforce_required=False
            )
            append_span(
                self.db,
                trace2,
                span_kind=SPAN_KIND_VALIDATE,
                name="validate",
                input_json={"answers": structured},
                output_json={"clean": clean, "errors": errors},
                latency_ms=_elapsed_ms(started),
                status=TRACE_STATUS_OK if not errors else TRACE_STATUS_ERROR,
                error=None if not errors else json.dumps(errors),
            )

        if errors:
            # Both attempts failed validation — surface to the human, never an
            # infinite loop, never a silent discard (AC-BI-25). Commit so the
            # traces + validate/retry spans survive.
            self.db.commit()
            return GenerateResult(ok=False, answers={}, field_errors=errors)

        # Commit the extraction trace(s) FIRST so they survive even if the
        # persist step below raises (a rare mid-grill BR delete) — a failed run
        # must never silently lose its trace (AC-BI-09). Persist then commits the
        # answers separately (write-only; NEVER promotes, AC-BI-27).
        self.db.commit()
        definition.persist_answers(self.db, tenant_id, target_id, clean, actor)
        self.db.commit()
        return GenerateResult(ok=True, answers=clean, field_errors={})

    # -- completion wrappers (decision 1) --------------------------------------
    def _complete(self, ctx, **kwargs) -> LLMResult:
        result, _ = self._complete_traced(ctx, **kwargs)
        return result

    def _complete_traced(
        self,
        ctx: GrillContext,
        *,
        conversation_id: str,
        system: str,
        messages: List[Dict[str, str]],
        output_schema: Optional[Dict[str, Any]],
        actor,
    ):
        """Run ONE traced completion. On ``LLMError`` the flushed trace is
        COMMITTED before a clean ``GrillError`` is raised (decision 1) — so a
        failed grill always leaves an ``error`` trace behind (AC-BI-24b)."""
        client = AiClient(self.db)
        try:
            return client.complete(
                tenant_id=ctx.tenant_id,
                agent=ctx.agent,
                system=system,
                messages=messages,
                output_schema=output_schema,
                conversation_id=conversation_id,
                skill_key=ctx.skill_key,
                prompt_version=ctx.prompt_version,
                actor_id=getattr(actor, "id", None),
            )
        except LLMError as exc:
            # Persist the flushed error trace + any messages written this turn,
            # THEN surface — the commit means get_db's teardown rollback is a
            # no-op and the trace is never lost.
            self.db.commit()
            raise GrillError(str(exc)) from exc


# ── helpers ───────────────────────────────────────────────────────────────────


def _target_type(definition: GrillDefinition) -> str:
    """The conversation ``target_type`` is the ideation BR status-entity key —
    passed through the context resolver via the definition. Kept as a small
    indirection so a second definition names its own target type."""
    return _DEFINITION_TARGET_TYPES.get(definition.key, definition.key)


# A definition declares its conversation target_type here (mirrors the status
# entity key). Set by the module when it registers the definition.
_DEFINITION_TARGET_TYPES: Dict[str, str] = {}


def set_definition_target_type(key: str, target_type: str) -> None:
    _DEFINITION_TARGET_TYPES[key] = target_type


def _valid_keys(ctx: GrillContext) -> set:
    return {f["key"] for f in ctx.target_fields if f.get("key")}


def _clean_covered(raw: Any, valid_keys: set) -> List[str]:
    if not isinstance(raw, list):
        return []
    seen: set = set()
    out: List[str] = []
    for item in raw:
        if isinstance(item, str) and item in valid_keys and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _field_lines(ctx: GrillContext) -> List[str]:
    return [f"{f['key']} — {f.get('label') or f['key']}" for f in ctx.target_fields if f.get("key")]


def _compose_system(ctx: GrillContext) -> str:
    """Compose the skill body against its injected variables (AC-BI-08,
    substitution ONLY). ``target_fields`` + ``source_artifacts`` are the two
    tokens every ``grill-me-business`` skill declares."""
    return compose(
        ctx.skill_body,
        {
            "target_fields": _field_lines(ctx),
            "source_artifacts": ctx.source_artifacts or ["(no linked source artifacts yet)"],
        },
    )


def _compose_extraction_system(ctx: GrillContext) -> str:
    """Extraction reuses the same grounded skill body, then appends the strict
    extraction directive (partial emit; never invent — AC-BI-26)."""
    base = _compose_system(ctx)
    directive = (
        "\n\n---\nEXTRACTION TASK: Read the ENTIRE conversation above and the "
        "linked source artifacts, then return ONLY structured output filling each "
        "target field with what the conversation actually established. A later "
        "answer overrides an earlier one. If a field was never grounded, leave it "
        "an EMPTY string — never invent a value. Do not add commentary."
    )
    return base + directive


def _extraction_messages(ctx: GrillContext, transcript) -> List[Dict[str, str]]:
    """The whole transcript as the extraction input (AC-BI-24). Source artifacts
    already ride the system prompt; the transcript carries the clarifications."""
    messages = [{"role": m.role, "content": m.content or ""} for m in transcript]
    if not messages:
        # Extraction before any turn: give the model the artifacts to work from.
        messages = [
            {
                "role": ROLE_USER,
                "content": "Extract the target fields from the linked source artifacts.",
            }
        ]
    return messages


def _turn_schema(ctx: GrillContext) -> Dict[str, Any]:
    """The turn's ONE structured output (AC-BI-24b): prose reply + the coverage
    map (answer-keys grounded so far), returned together in a single call."""
    keys = [f["key"] for f in ctx.target_fields if f.get("key")]
    return {
        "type": "object",
        "properties": {
            "replyText": {
                "type": "string",
                "description": "Your next grilling question or acknowledgement to the user.",
            },
            "coveredFields": {
                "type": "array",
                "items": {"type": "string", "enum": keys},
                "description": "Target field keys the conversation has grounded SO FAR.",
            },
        },
        "required": ["replyText", "coveredFields"],
    }


def _structured(result: LLMResult) -> Dict[str, Any]:
    if isinstance(result.structured, dict):
        return result.structured
    # A provider that returned text where structured was requested — treat as an
    # empty extraction (partial emit); the retry/validate path still runs.
    return {}


def _parse_turn(result: LLMResult, valid_keys: set):
    structured = _structured(result)
    reply = structured.get("replyText")
    if not isinstance(reply, str) or not reply.strip():
        reply = result.text or "Could you tell me more?"
    covered = _clean_covered(structured.get("coveredFields"), valid_keys)
    return reply, covered


def _retry_instruction(errors: Dict[str, str]) -> str:
    lines = "\n".join(f"- {k}: {v}" for k, v in errors.items())
    return (
        "The previous structured output failed validation for these fields:\n"
        f"{lines}\n"
        "Return corrected structured output. Leave a field an empty string rather "
        "than inventing a value."
    )


__all__ = [
    "GrillDefinition",
    "GrillContext",
    "GrillEngine",
    "GrillError",
    "GrillState",
    "TurnResult",
    "GenerateResult",
    "register_grill_definition",
    "get_grill_definition",
    "set_definition_target_type",
]

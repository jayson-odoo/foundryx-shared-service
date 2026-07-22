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
    # The running per-field captured summary the panel renders (AC-BI-24c).
    captured_summary: Dict[str, str]
    # The model's finalize-intent signal; the APP fires Generate on it (AC-BI-24c).
    generate_signal: bool


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
    # The latest assistant turn's captured summary (AC-BI-24c) — carried so the
    # panel survives a reload / a returned-to-later session (durable draft).
    captured_summary: Dict[str, str]


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
        summary: Dict[str, str] = {}
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
                    # ACCUMULATE across ALL assistant turns (AC-BI-29c): a later
                    # turn that reports only the field it just discussed must NEVER
                    # drop an earlier-captured field. Fold every turn's map onto the
                    # running state (latest value wins per field) so a reload / a
                    # returned-to-later session shows the FULL captured set — never
                    # just the last turn's. Robust even against legacy rows that
                    # stored a single turn's partial map.
                    covered = _merge_covered(covered, covered_fields)
                    summary = _merge_summary(
                        summary, _clean_summary(m.captured_summary_json, valid_keys)
                    )
        return GrillState(
            fields=ctx.target_fields,
            messages=messages,
            covered_fields=covered,
            captured_summary=summary,
        )

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
        reply_text, covered, summary, generate_signal = _parse_turn(result, valid_keys)
        # ACCUMULATE (AC-BI-29c): merge this turn's coverage/summary onto the
        # cumulative state folded from every prior assistant turn (latest value
        # wins per field), and STORE the cumulative on the new assistant row so a
        # reload is correct too. A turn that only mentions the field it just
        # discussed can never make an earlier-captured field vanish
        # ("2 of 6" → "1 of 6"). ``prior`` was read before the new turns were
        # added, so it holds exactly the transcript up to now.
        prior_summary, prior_covered = _accumulate(prior, valid_keys)
        covered = _merge_covered(prior_covered, covered)
        summary = _merge_summary(prior_summary, summary)
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
            captured_summary=summary,
        )
        self.db.commit()
        return TurnResult(
            reply_text=reply_text,
            covered_fields=covered,
            captured_summary=summary,
            generate_signal=generate_signal,
        )

    # -- opening turn (no user message) ----------------------------------------
    def open(
        self, definition: GrillDefinition, tenant_id: str, target_id: str, actor
    ) -> TurnResult:
        """Produce the FIRST assistant message with NO user message (AC-BI-29b):
        the grill greets, summarizes the absorbed source artifact(s) and asks its
        first clarifying question, grounded in the linked ideas.

        Idempotent — if the transcript is already non-empty this returns the latest
        assistant reply WITHOUT another LLM call, so a double-fire (a re-render /
        two racing requests) never produces two opening messages or a wasted call.
        Like every completion here, an ``LLMError`` commits the flushed trace
        first, then surfaces ``GrillError`` (decision 1 / AC-BI-24b)."""
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
        valid_keys = _valid_keys(ctx)
        prior = self.convos.messages(convo.id)
        if prior:
            last = next(
                (m for m in reversed(prior) if m.role == ROLE_ASSISTANT), None
            )
            if last is not None:
                return TurnResult(
                    reply_text=last.content or "",
                    covered_fields=_clean_covered(last.covered_fields_json, valid_keys),
                    captured_summary=_clean_summary(last.captured_summary_json, valid_keys),
                    generate_signal=False,
                )

        system = _compose_system(ctx)
        schema = _turn_schema(ctx)
        # A synthetic, NON-persisted user directive drives the opening — the model
        # needs something to respond to, but the transcript starts with only the
        # assistant greeting (no user turn is stored).
        opening = [{"role": ROLE_USER, "content": _opening_instruction()}]
        result = self._complete(
            ctx,
            conversation_id=convo.id,
            system=system,
            messages=opening,
            output_schema=schema,
            actor=actor,
        )
        reply_text, covered, summary, generate_signal = _parse_turn(result, valid_keys)
        self.convos.add_message(
            conversation_id=convo.id,
            tenant_id=tenant_id,
            role=ROLE_ASSISTANT,
            content=reply_text,
            covered_fields=covered,
            captured_summary=summary,
        )
        self.db.commit()
        return TurnResult(
            reply_text=reply_text,
            covered_fields=covered,
            captured_summary=summary,
            generate_signal=generate_signal,
        )

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
        # required=True (AC-BI-24c): mark EVERY target key required so the model
        # returns a value for each field — including one synthesized across turns
        # or a negative answer. The paired directive keeps genuinely-ungrounded
        # fields blank (never invented) and validate stays enforce_required=False.
        schema = field_schema(ctx.target_fields, required=True)

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


def _merge_covered(base: List[str], incoming: List[str]) -> List[str]:
    """Union two covered-field lists preserving order (AC-BI-29c) — coverage is
    monotonic: a field once grounded stays grounded."""
    out = list(base)
    seen = set(base)
    for key in incoming:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _merge_summary(base: Dict[str, str], incoming: Dict[str, str]) -> Dict[str, str]:
    """Merge two captured-summary maps, latest non-blank value winning per field
    (AC-BI-29c). A field absent from ``incoming`` keeps its prior value — never
    dropped just because a later turn didn't mention it. ``incoming`` is already
    ``_clean_summary``-coerced (str, non-blank), but re-guard defensively."""
    out = dict(base)
    for key, value in incoming.items():
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _accumulate(messages, valid_keys: set):
    """Fold the running (summary, covered) cumulative state over every ASSISTANT
    turn in ``messages`` (AC-BI-29c) — the authoritative merged capture the panel
    renders, independent of whether individual rows stored a partial map."""
    covered: List[str] = []
    summary: Dict[str, str] = {}
    for m in messages:
        if m.role == ROLE_ASSISTANT:
            covered = _merge_covered(covered, _clean_covered(m.covered_fields_json, valid_keys))
            summary = _merge_summary(summary, _clean_summary(m.captured_summary_json, valid_keys))
    return summary, covered


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
        "linked source artifacts, then return ONLY structured output. Return a "
        "value for EVERY field in the schema. For a field discussed across "
        "several turns, SYNTHESIZE the final agreed answer from the whole "
        "conversation. A negative answer (e.g. 'no constraints', 'none') is still "
        "a value — state it plainly. A later answer overrides an earlier one. "
        "Only leave a field an EMPTY string if it was GENUINELY never discussed — "
        "NEVER invent a value to fill a field. Do not add commentary."
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
    """The turn's ONE structured output (AC-BI-24b + 24c): prose reply + the
    coverage map + a running captured summary + a generate signal, returned
    together in a single call so the panel updates each turn with NO extra
    extraction pass (AC-BI-24c).

    - ``capturedSummary`` = a ``{fieldKey: shortValue}`` map of what the
      conversation has understood so far (values only — the panel renders them).
    - ``generateSignal`` = TRUE only when the user's LATEST message clearly asks
      to finalize/generate ("generate it", "that's enough"). The MODEL signals;
      the APP fires Generate (D22-A: the model gains no side-effect tool).
    """
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
            # A LIST of {key, value} — NOT a nested object with per-field
            # properties. gemini-2.5-flash runs away to MAX_TOKENS on a nested
            # object property here even with thinking off (live-verified, the S3
            # runaway class); the enum-keyed array shape (like coveredFields)
            # decodes cleanly. `_clean_summary` folds it back to a {key: value}
            # map for the wire.
            "capturedSummary": {
                "type": "array",
                "description": (
                    "The target fields established so far, each with a concise "
                    "current value. Omit a field not yet discussed. Values only — "
                    "no commentary."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": keys},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                },
            },
            "generateSignal": {
                "type": "boolean",
                "description": (
                    "TRUE only if the user's latest message clearly asks to "
                    "finalize or generate the requirement now (e.g. 'generate it', "
                    "'create the BR', 'that's enough', 'looks good, make it'). "
                    "FALSE for a normal answer or question."
                ),
            },
        },
        "required": ["replyText", "coveredFields", "capturedSummary", "generateSignal"],
    }


def _structured(result: LLMResult) -> Dict[str, Any]:
    if isinstance(result.structured, dict):
        return result.structured
    # A provider that returned text where structured was requested — treat as an
    # empty extraction (partial emit); the retry/validate path still runs.
    return {}


def _clean_summary(raw: Any, valid_keys: set) -> Dict[str, str]:
    """Coerce the model's ``capturedSummary`` to a ``{validKey: str}`` map — drop
    unknown keys (defense, like ``coveredFields``) and non-string / blank values
    so the panel only ever renders grounded target fields.

    Accepts BOTH shapes: the wire/model list-of-``{key, value}`` (the enum-keyed
    array the turn schema requests — a nested object property runs Gemini away,
    the S3 runaway class) AND a plain ``{key: value}`` dict (a persisted map, or a
    stub/other-provider fallback)."""

    def _put(out: Dict[str, str], key: Any, value: Any) -> None:
        if not isinstance(key, str) or key not in valid_keys:
            return
        text = value if isinstance(value, str) else ("" if value is None else str(value))
        text = text.strip()
        if text:
            out[key] = text

    out: Dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                _put(out, item.get("key"), item.get("value"))
    elif isinstance(raw, dict):
        for key, value in raw.items():
            _put(out, key, value)
    return out


def _parse_turn(result: LLMResult, valid_keys: set):
    structured = _structured(result)
    reply = structured.get("replyText")
    if not isinstance(reply, str) or not reply.strip():
        reply = result.text or "Could you tell me more?"
    covered = _clean_covered(structured.get("coveredFields"), valid_keys)
    summary = _clean_summary(structured.get("capturedSummary"), valid_keys)
    generate_signal = structured.get("generateSignal") is True
    return reply, covered, summary, generate_signal


def _opening_instruction() -> str:
    """The synthetic directive that drives the opening turn (AC-BI-29b) — greet,
    summarize the grounded source artifacts, ask ONE first clarifying question.
    Substitution-only content already rode the system prompt; this is a fixed
    instruction, never tenant input."""
    return (
        "Begin the session now. In a warm, brief greeting: (1) summarize in one or "
        "two sentences what you understand from the linked source artifacts above, "
        "then (2) ask your FIRST clarifying question to start filling the target "
        "fields. Ask only ONE question. Do not invent details the artifacts do not "
        "contain. In coveredFields, include any target field the linked source "
        "artifacts ALREADY establish (do not leave a field the artifacts clearly "
        "answer marked as uncovered), and give its value in capturedSummary. Set "
        "generateSignal to false — the interview is only beginning."
    )


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

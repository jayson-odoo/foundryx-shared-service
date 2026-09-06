"""Deterministic stub LLM adapter (AC-BI-12) - mirrors omnichannel's `_is_dev`.

`is_dev(connection)` is true when there is **no active LLM connection at all**
or when the resolved connection carries `dev` credentials. Under it, pytest,
Vitest and browser-automation E2E runs proceed with zero API key, zero cost and
zero network.

**Only the provider HTTP call is faked.** The grill engine, coverage tracking,
`form_engine` validation, status transitions and RBAC all execute for real - the
stub substitutes for `LLMProvider.complete`/`models` and nothing else.

**Fixture-driven.** A spec declares exactly what the "model" returns - including
an invalid extraction or one missing a required field - so the retry path, the
partial-emit path and the never-auto-promote guard are all deterministically
testable:

    with stub_fixtures(StubResponse(structured={"problem_statement": "x"})):
        ...                       # one queued response, then back to default

Queued fixtures are consumed in order; once the queue drains the stub falls back
to its deterministic derived response, so a test never hangs on an empty queue.
"""
import hashlib
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from app.integrations.base import LLMError, LLMResult, ModelOption

STUB_PROVIDER = "stub"
STUB_MODEL = "stub-model-1"


@dataclass
class StubResponse:
    """One scripted reply. `error` wins; then `structured`; then `text`."""

    text: Optional[str] = None
    structured: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    tokens_in: int = 11
    tokens_out: int = 7


@dataclass
class _StubState:
    queue: List[StubResponse] = field(default_factory=list)


# Thread-local so a stub script in one test can never bleed into another (the
# dispatcher/beat threads share this process).
_local = threading.local()


def _state() -> _StubState:
    existing = getattr(_local, "state", None)
    if existing is None:
        existing = _StubState()
        _local.state = existing
    return existing


def queue_stub_responses(*responses: StubResponse) -> None:
    """Script the next N stub replies (consumed in order)."""
    _state().queue.extend(responses)


def clear_stub_responses() -> None:
    _state().queue.clear()


@contextmanager
def stub_fixtures(*responses: StubResponse) -> Iterator[None]:
    """Scope a stub script to a block, restoring the previous queue after."""
    previous = list(_state().queue)
    _state().queue = list(responses)
    try:
        yield
    finally:
        _state().queue = previous


def is_dev(credentials: Optional[Dict[str, Any]], *, has_connection: bool) -> bool:
    """The omnichannel `_is_dev` shape: no connection at all, or dev creds."""
    if not has_connection:
        return True
    return bool((credentials or {}).get("dev"))


def _derive(system: str, messages: List[Dict[str, str]]) -> str:
    """A stable, readable pseudo-reply - same input always yields the same
    output, so snapshots and E2E assertions never flake."""
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
    )
    digest = hashlib.sha256(
        json.dumps([system, [m.get("content", "") for m in messages]], sort_keys=True).encode()
    ).hexdigest()[:8]
    snippet = (last_user or "").strip()[:120]
    return f"[stub:{digest}] {snippet}" if snippet else f"[stub:{digest}]"


def _derive_structured(output_schema: Dict[str, Any], seed: str) -> Dict[str, Any]:
    """A schema-shaped object filled with deterministic placeholder strings.

    Only STRING properties are populated; anything else is left out, which is a
    valid partial emit - the stub must never fabricate a shape the real models
    wouldn't (Bi-D13: partial emit is success, invention is not).
    """
    properties = output_schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    result: Dict[str, Any] = {}
    for key, spec in properties.items():
        if isinstance(spec, dict) and spec.get("type") == "string":
            result[key] = f"[stub:{seed}] {key}"
    return result


def _norm_words(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _find_evidence(message: str, candidates: List[str]) -> Optional[str]:
    """First candidate phrase present in the message (case-insensitive, `_`
    and `-` read as spaces). Returns the EXACT message slice so the reducer's
    evidence check passes."""
    lowered = message.lower()
    for candidate in candidates:
        variants = {candidate.lower(), _norm_words(candidate)}
        for variant in variants:
            if not variant:
                continue
            idx = lowered.find(variant)
            if idx >= 0:
                return message[idx : idx + len(variant)]
    return None


def _derive_stateful(output_schema: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Deterministic, evidence-backed patches for the STATEFUL AI Agent
    contract (plan sprint-4/19) so the seeded progress-update proof and E2E
    run with no LLM key. Rules, in order, per stateful field:

    * enum: the first configured choice spelled in the message is `set`
      (evidence = that exact slice);
    * a field targeted by the pending clarification is `set` to the whole
      message (a short answer resolves the question);
    * `<key>: value` spelled in the message sets that field;
    * the first missing required text field with no pending question takes
      the whole message (the opening message names the task);
    * everything else is `no_change`.

    Transient outputs: every enum output whose choices contain a readiness
    pair (`ready` vs anything else) becomes `ready` when all required
    stateful fields are known, else the other choice; every text output
    becomes either a question about the first missing required field or a
    confirmation listing the accepted state. `pendingField` names the field
    asked about (or null)."""
    try:
        payload = json.loads(next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "{}"))
    except (ValueError, TypeError):
        payload = {}
    message = str(payload.get("currentMessage") or "")
    accepted = payload.get("acceptedState") if isinstance(payload.get("acceptedState"), dict) else {}
    params = payload.get("outputParameters") if isinstance(payload.get("outputParameters"), list) else []
    pending = payload.get("pendingClarification") if isinstance(payload.get("pendingClarification"), dict) else None
    stateful = [p for p in params if isinstance(p, dict) and p.get("stateful") is True]
    transient = [p for p in params if isinstance(p, dict) and p.get("stateful") is not True]

    patches: Dict[str, Any] = {}
    known: Dict[str, Any] = dict(accepted)
    lowered = message.lower()
    # A message that is nothing but an enum choice ("blocked", "in progress")
    # never doubles as the value of a text field.
    enum_words = [
        v for row in stateful if row.get("type") == "enum"
        for v in (row.get("enumValues") or []) if isinstance(v, str)
    ]
    text_claimed = _norm_words(message) in {_norm_words(v) for v in enum_words}
    for row in stateful:
        key = row["key"]
        patch: Dict[str, Any] = {"operation": "no_change"}
        if row.get("type") == "enum":
            evidence = _find_evidence(message, [v for v in row.get("enumValues") or [] if isinstance(v, str)])
            if evidence is not None:
                value = next(v for v in row["enumValues"] if _norm_words(v) == _norm_words(evidence))
                patch = {"operation": "set", "value": value, "evidence": evidence}
        elif row.get("type") == "string":
            marker = f"{key.lower()}:"
            if pending and pending.get("field") == key and message.strip():
                patch = {"operation": "set", "value": message.strip(), "evidence": message.strip()}
            elif marker in lowered:
                idx = lowered.index(marker) + len(marker)
                rest = message[idx:].strip()
                tail = rest.split(".")[0].strip() if rest else ""
                if tail:
                    patch = {"operation": "set", "value": tail, "evidence": tail}
            elif key not in known and row.get("required") and not pending and not text_claimed and message.strip():
                patch = {"operation": "set", "value": message.strip(), "evidence": message.strip()}
                text_claimed = True
        elif row.get("type") == "boolean":
            evidence = _find_evidence(message, ["yes", "no", "true", "false"])
            if evidence is not None:
                patch = {"operation": "set", "value": evidence.lower() in ("yes", "true"), "evidence": evidence}
        if patch.get("operation") == "set":
            known[key] = patch["value"]
        patches[key] = patch

    missing = [row for row in stateful if row.get("required") and row["key"] not in known]
    # A blocked status without a stated blocker asks for it (demo semantics
    # via config: any optional text field whose key appears in an enum value).
    if not missing:
        for row in stateful:
            if row.get("type") == "string" and row["key"] not in known and any(
                isinstance(v, str) and str(known.get(p["key"], "")).lower().startswith(row["key"].lower()[:5])
                for p in stateful if p.get("type") == "enum" for v in (p.get("enumValues") or [])
            ):
                missing = [row]
                break
    ask = missing[0] if missing else None

    outputs: Dict[str, Any] = {}
    for row in transient:
        if row.get("type") == "enum":
            choices = [v for v in row.get("enumValues") or [] if isinstance(v, str)]
            ready = next((v for v in choices if v.lower() == "ready"), None)
            other = next((v for v in choices if v != ready), None)
            if ready is not None and other is not None:
                outputs[row["key"]] = ready if ask is None else other
            elif choices:
                outputs[row["key"]] = choices[0]
        elif row.get("type") == "string":
            if ask is not None:
                outputs[row["key"]] = f"What is the {ask['key'].replace('_', ' ')}?"
            else:
                summary = ", ".join(f"{k} = {v}" for k, v in known.items() if k in {r['key'] for r in stateful})
                outputs[row["key"]] = f"Recorded: {summary}."
        elif row.get("type") == "boolean":
            outputs[row["key"]] = ask is None
        elif row.get("type") == "number":
            outputs[row["key"]] = len(known)
    return {"outputs": outputs, "statePatches": patches, "pendingField": ask["key"] if ask else None}


class StubLLMProvider:
    """Stands in for any `LLMProvider`. Same shape, no network."""

    provider = STUB_PROVIDER
    type = "llm"
    title = "Stub (development)"
    description = "Deterministic offline responses - no API key, no cost, no network."
    icon = "flask-conical"
    test_label = "Verify key"
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return []

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ):
        from app.integrations.base import TestResult  # noqa: PLC0415 - avoid a cycle

        return TestResult(ok=True, message="Stub adapter - no provider contacted.")

    def models(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> List[ModelOption]:
        return [ModelOption(id=STUB_MODEL, label="Stub model", created=0)]

    def complete(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        model: str,
        system: str,
        messages: List[Dict[str, str]],
        output_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0,
    ) -> LLMResult:
        state = _state()
        scripted = state.queue.pop(0) if state.queue else None

        if scripted is not None and scripted.error:
            raise LLMError(scripted.error)

        if scripted is not None and scripted.structured is not None:
            return LLMResult(
                structured=scripted.structured,
                tokens_in=scripted.tokens_in,
                tokens_out=scripted.tokens_out,
                model=model or STUB_MODEL,
                finish_reason="stop",
            )
        if scripted is not None and scripted.text is not None:
            return LLMResult(
                text=scripted.text,
                tokens_in=scripted.tokens_in,
                tokens_out=scripted.tokens_out,
                model=model or STUB_MODEL,
                finish_reason="stop",
            )

        derived = _derive(system, messages)
        if output_schema is not None and "statePatches" in (output_schema.get("properties") or {}):
            return LLMResult(
                structured=_derive_stateful(output_schema, messages),
                tokens_in=11,
                tokens_out=7,
                model=model or STUB_MODEL,
                finish_reason="stop",
            )
        if output_schema is not None:
            return LLMResult(
                structured=_derive_structured(output_schema, derived[6:14]),
                tokens_in=11,
                tokens_out=7,
                model=model or STUB_MODEL,
                finish_reason="stop",
            )
        return LLMResult(
            text=derived,
            tokens_in=11,
            tokens_out=7,
            model=model or STUB_MODEL,
            finish_reason="stop",
        )


stub_provider = StubLLMProvider()

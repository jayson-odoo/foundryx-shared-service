"""Deterministic stub LLM adapter (AC-BI-12) - mirrors omnichannel's `_is_dev`.

`is_dev(connection)` is true when there is **no active LLM connection at all**
or when the resolved connection carries `dev` credentials. Under it, pytest,
Vitest and Playwright run with zero API key, zero cost and zero network.

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

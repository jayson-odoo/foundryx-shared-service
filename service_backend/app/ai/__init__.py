"""Core AI subsystem (Phase B-i slice 1) — CORE, not a module (Bi-D2).

The public surface every consumer uses:

- `AiClient.complete(...)` — the one traced completion seam (plan §7). No caller
  ever touches a vendor SDK or branches on provider.
- `compose(body, variables)` — substitution-only prompt composition (AC-BI-08).
- `TraceWriter` — OTel-GenAI-shaped trace/span writer with payload caps.
- `stub_fixtures(...)` — script the deterministic stub adapter in a test.
"""
from app.ai.client import AiClient, ResolvedConnection, any_llm_connection, resolve_for_agent
from app.ai.prompt import compose, field_schema
from app.ai.retention import prune_traces
from app.ai.stub import (
    STUB_MODEL,
    STUB_PROVIDER,
    StubResponse,
    clear_stub_responses,
    is_dev,
    queue_stub_responses,
    stub_fixtures,
    stub_provider,
)
from app.ai.tracing import TraceWriter, cap_payload

__all__ = [
    "AiClient",
    "ResolvedConnection",
    "any_llm_connection",
    "resolve_for_agent",
    "compose",
    "field_schema",
    "prune_traces",
    "TraceWriter",
    "cap_payload",
    "StubResponse",
    "stub_fixtures",
    "queue_stub_responses",
    "clear_stub_responses",
    "stub_provider",
    "is_dev",
    "STUB_PROVIDER",
    "STUB_MODEL",
]

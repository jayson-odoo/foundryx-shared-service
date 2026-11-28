"""The builder turn (contract 3.1 + 5): the model proposes operations, SS applies and VALIDATES them.

Understanding the request is the model's job; nothing here guesses at the user's words. The validator
(``spec.py``) is the gate: whatever the model emits, the draft SS returns passes section 2 and the
catalogue it was given (for the tiles this turn added or changed). The catalogue, draft, refusals and
history go to the model as JSON DATA, never as instructions. One LLM call, plus ONE retry carrying the
validator's problems, then ``ai_failed``. Exactly one ``dash_usage`` row per turn, written before answering.

Reuses core's ``AiClient.complete`` (no second LLM client) through a seeded system agent per tenant,
key ``dashboard-builder``, ensured lazily on the first turn (existing tenants need no backfill).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.client import AiClient, any_llm_connection
from app.config import settings
from app.integrations.base import LLMError
from app.models.ai import AiAgent
from app.repositories.ai_repository import AgentRepository

from .. import schemas
from ..gateway_auth import DashKey
from ..models import DashUsage
from ..repositories.usage_repository import UsageRepository
from ..spec import validate_against_catalogue, validate_catalogue, validate_spec
from . import ops as ops_mod
from .builder_prompt import OUTPUT_SCHEMA, SYSTEM_PROMPT
from .errors import DashError, spec_invalid
from .store_service import DashboardStore

AGENT_KEY = "dashboard-builder"
AGENT_NAME = "Dashboard builder"
AGENT_DESCRIPTION = "Turns a request into changes to a dashboard specification."
FEATURE = "dashboard_builder"

class BuilderService:
    def __init__(self, db: Session, key: DashKey):
        self.db = db
        self.key = key

    # -- agent ---------------------------------------------------------------------------------------
    def _agent(self) -> AiAgent:
        repo = AgentRepository(self.db)
        agent = repo.get_by_key(self.key.tenant_id, AGENT_KEY)
        connection = any_llm_connection(self.db, self.key.tenant_id)
        if agent is None:
            agent = repo.add(AiAgent(
                tenant_id=self.key.tenant_id, key=AGENT_KEY, is_system=True, name=AGENT_NAME,
                description=AGENT_DESCRIPTION, connection_id=connection.id if connection else None,
                model="", temperature=0.0, is_enabled=True,
            ))
        elif not agent.connection_id and connection is not None:
            agent.connection_id = connection.id
        self.db.commit()
        return agent

    # -- the turn ------------------------------------------------------------------------------------
    def turn(self, body: schemas.TurnRequest) -> Dict[str, Any]:
        problems = validate_spec(body.draft)
        if problems:
            raise spec_invalid(problems, "The dashboard sent with the request is not valid.")
        problems = validate_catalogue(body.catalogue)
        if problems:
            raise spec_invalid(problems, "The list of available data is not valid.")
        if body.dashboard_id is not None:
            DashboardStore(self.db, self.key).owned(body.dashboard_id, body.actor_ref)
        if any_llm_connection(self.db, self.key.tenant_id) is None and settings.environment != "development":
            raise DashError(409, "ai_not_configured", "No AI connection is set up for this tenant.")

        agent = self._agent()
        data = {
            "draft": body.draft, "catalogue": body.catalogue,
            "refusals": body.refusals, "history": [h.model_dump() for h in body.history],
        }
        system = SYSTEM_PROMPT + "\n\nDATA\n" + json.dumps(data, ensure_ascii=False)
        messages: List[Dict[str, str]] = [{"role": "user", "content": body.message}]
        meter = _Meter()
        try:
            applied, reply = self._attempt(agent, system, messages, body, meter)
            if applied.problems:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps({"reply": reply, "operations": meter.last_ops}, ensure_ascii=False)},
                    {"role": "user", "content": json.dumps({
                        "problems": applied.problems,
                        "instruction": "The changes above were refused for these reasons. Reply again with corrected operations, starting from the same draft.",
                    }, ensure_ascii=False)},
                ]
                applied, reply = self._attempt(agent, system, messages, body, meter)
        except LLMError:
            self._log(body, agent, meter)
            raise DashError(502, "ai_failed", "The builder could not produce a dashboard. Nothing was saved.")
        self._log(body, agent, meter)
        if applied.problems:
            raise DashError(502, "ai_failed", "The builder could not produce a valid dashboard. Nothing was saved.")
        return schemas.TurnResponse(
            draft=applied.draft, operations=applied.operations, changed_tile_ids=applied.changed_tile_ids,
            reply=reply, question=schemas.Question(**applied.question) if applied.question else None,
            usage=schemas.TurnUsage(tokens_in=meter.tokens_in, tokens_out=meter.tokens_out, model=meter.model or agent.model or ""),
        ).model_dump(mode="json")

    def _attempt(self, agent: AiAgent, system: str, messages: List[Dict[str, str]], body: schemas.TurnRequest,
                 meter: "_Meter") -> Tuple[ops_mod.Applied, str]:
        started = time.monotonic()
        result, trace = self._call_model(agent, system, messages)
        meter.add(result, trace, int((time.monotonic() - started) * 1000))
        out = result.structured if isinstance(result.structured, dict) else {}
        reply = out.get("reply") if isinstance(out.get("reply"), str) else ""
        operations = out.get("operations", [])
        meter.last_ops = operations if isinstance(operations, list) else []
        applied = ops_mod.apply_operations(body.draft, operations)
        if not applied.problems and applied.question is None:
            applied.problems = self._validate(applied, body.catalogue)
        return applied, reply[:1000]

    def _call_model(self, agent: AiAgent, system: str, messages: List[Dict[str, str]]):
        """The ONE place the LLM is called (core's AiClient). The prompt lives in ``builder_prompt.py``
        and the model is the agent's / connection's default; swap either without touching the rest."""
        return AiClient(self.db).complete(
            tenant_id=self.key.tenant_id, agent=agent, system=system, messages=messages,
            output_schema=OUTPUT_SCHEMA, actor_id=None,
        )

    def _validate(self, applied: ops_mod.Applied, catalogue: Dict[str, Any]) -> List[Dict[str, str]]:
        problems = validate_spec(applied.draft)
        if problems:
            return problems
        # The catalogue is the gate for what THIS turn added or changed; a chart the turn left alone
        # (e.g. one the viewer lost access to since) is the product's "No access", not a refusal here.
        touched = {i for i, t in enumerate(applied.draft["tiles"]) if t.get("id") in set(applied.changed_tile_ids)}
        return [p for p in validate_against_catalogue(applied.draft, catalogue)
                if any(p["path"].startswith(f"tiles[{i}]") for i in touched)]

    def _log(self, body: schemas.TurnRequest, agent: AiAgent, meter: "_Meter") -> None:
        if meter.calls == 0:
            return
        UsageRepository(self.db, self.key.tenant_id, self.key.product).add(DashUsage(
            feature=FEATURE, dashboard_id=body.dashboard_id, actor_ref=body.actor_ref,
            provider=meter.provider, model=meter.model or agent.model or "", tokens_in=meter.tokens_in,
            tokens_out=meter.tokens_out, latency_ms=meter.latency_ms, llm_calls=meter.calls, trace_id=meter.trace_id,
        ))


class _Meter:
    """Tokens and calls summed over the turn (the first call plus the one retry)."""

    def __init__(self) -> None:
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.latency_ms = 0
        self.model = ""
        self.provider: Optional[str] = None
        self.trace_id: Optional[str] = None
        self.last_ops: List[Any] = []

    def add(self, result, trace, latency_ms: int) -> None:
        self.calls += 1
        self.tokens_in += int(result.tokens_in or 0)
        self.tokens_out += int(result.tokens_out or 0)
        self.latency_ms += latency_ms
        self.model = result.model or self.model
        self.provider = getattr(trace, "provider", None) or self.provider
        self.trace_id = getattr(trace, "id", None) or self.trace_id

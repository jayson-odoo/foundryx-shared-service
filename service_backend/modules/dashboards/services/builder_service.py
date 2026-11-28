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

import copy
import json
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import base64
import binascii

from app.ai.client import AiClient, any_llm_connection
from app.config import settings
from app.integrations.base import LLMError
from app.models.ai import AiAgent
from app.repositories.ai_repository import AgentRepository

from .. import schemas
from ..gateway_auth import DashKey
from ..models import DashUsage
from ..repositories.connection_repository import ConnectionRepository
from ..repositories.usage_repository import UsageRepository
from ..spec import validate_against_catalogue, validate_catalogue, validate_refusals, validate_spec
from . import ops as ops_mod
from .builder_prompt import OUTPUT_SCHEMA, SYSTEM_PROMPT
from .errors import DashError, spec_invalid
from .store_service import DashboardStore

AGENT_KEY = "dashboard-builder"
AGENT_NAME = "Dashboard builder"
AGENT_DESCRIPTION = "Turns a request into changes to a dashboard specification."
FEATURE = "dashboard_builder"
# The builder model (owner ruling 28 Nov): set on the seeded agent; an existing agent with no model gets it.
BUILDER_MODEL = "claude-sonnet-5-5"
BUILDER_PROVIDER = "anthropic"
# Crew ruling (a): the catalogue gates only the tiles THIS turn added or changed; schema + rules gate the whole draft.
CATALOGUE_CHECKS_TOUCHED_TILES_ONLY = True

MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_TOTAL_BYTES = 15 * 1024 * 1024
MAX_IMAGE_BASE64_CHARS = -(-MAX_IMAGE_BYTES * 4 // 3) + 4  # ceil(5 MB * 4/3) + padding
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")

class BuilderService:
    def __init__(self, db: Session, key: DashKey):
        self.db = db
        self.key = key

    # -- agent ---------------------------------------------------------------------------------------
    def _agent(self) -> AiAgent:
        repo = AgentRepository(self.db)
        agent = repo.get_by_key(self.key.tenant_id, AGENT_KEY)
        connection = ConnectionRepository(self.db).llm_for_provider(self.key.tenant_id, BUILDER_PROVIDER)
        if agent is None:
            agent = repo.add(AiAgent(
                tenant_id=self.key.tenant_id, key=AGENT_KEY, is_system=True, name=AGENT_NAME,
                description=AGENT_DESCRIPTION, connection_id=connection.id if connection else None,
                model=BUILDER_MODEL, temperature=0.0, is_enabled=True,
            ))
        else:
            if connection is not None and not ConnectionRepository(self.db).usable(
                    self.key.tenant_id, agent.connection_id, BUILDER_PROVIDER):
                agent.connection_id = connection.id
            if not agent.model:
                agent.model = BUILDER_MODEL
        self.db.commit()
        return agent

    def _require_connection(self) -> None:
        """409 before AiClient is ever handed an agent that would raise. An Anthropic connection is needed;
        only a tenant with NO LLM connection at all, in development, falls through to the stub."""
        if ConnectionRepository(self.db).llm_for_provider(self.key.tenant_id, BUILDER_PROVIDER) is not None:
            return
        if any_llm_connection(self.db, self.key.tenant_id) is not None:
            raise DashError(409, "ai_not_configured", "The dashboard builder needs an Anthropic AI connection.")
        if settings.environment != "development":
            raise DashError(409, "ai_not_configured", "No AI connection is set up for this tenant.")

    # -- the turn ------------------------------------------------------------------------------------
    def turn(self, body: schemas.TurnRequest) -> Dict[str, Any]:
        problems = validate_spec(body.draft)
        if problems:
            raise spec_invalid(problems, "The dashboard sent with the request is not valid.")
        problems = validate_catalogue(body.catalogue)
        if problems:
            raise spec_invalid(problems, "The list of available data is not valid.")
        images = _check_images(body.images)  # before any model call
        problems = validate_refusals(body.refusals)
        if problems:
            raise spec_invalid(problems, "The refused charts sent with the request are not valid.")
        if body.dashboard_id is not None:
            DashboardStore(self.db, self.key).owned(body.dashboard_id, body.actor_ref)
        self._require_connection()

        agent = self._agent()
        data = {
            "draft": body.draft, "catalogue": body.catalogue,
            "refusals": body.refusals, "history": [h.model_dump() for h in body.history],
        }
        system = SYSTEM_PROMPT + "\n\nDATA\n" + json.dumps(data, ensure_ascii=False)
        content: Any = body.message
        if images:
            content = [{"type": "image", "source": {"type": "base64", "media_type": i["media_type"], "data": i["data_base64"]}}
                       for i in images] + [{"type": "text", "text": body.message}]
        messages: List[Dict[str, Any]] = [{"role": "user", "content": content}]
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
            self._log(body, agent, meter, len(images))
            raise DashError(502, "ai_failed", "The builder could not produce a dashboard. Nothing was saved.")
        self._log(body, agent, meter, len(images))
        if applied.problems:
            raise DashError(502, "ai_failed", "The builder could not produce a valid dashboard. Nothing was saved.")
        usage = schemas.TurnUsage(tokens_in=meter.tokens_in, tokens_out=meter.tokens_out, model=meter.model or agent.model or "")
        if applied.need_entities:
            return schemas.TurnResponse(
                draft=applied.draft, changed_tile_ids=[], reply=None, question=None,
                need_entities=applied.need_entities, usage=usage,
            ).model_dump(mode="json", exclude={"operations"})
        return schemas.TurnResponse(
            draft=applied.draft, operations=applied.operations, changed_tile_ids=applied.changed_tile_ids,
            reply=reply, question=schemas.Question(**applied.question) if applied.question else None, usage=usage,
        ).model_dump(mode="json", exclude={"need_entities"})

    def _attempt(self, agent: AiAgent, system: str, messages: List[Dict[str, Any]], body: schemas.TurnRequest,
                 meter: "_Meter") -> Tuple[ops_mod.Applied, str]:
        started = time.monotonic()
        meter.calls += 1  # counted when attempted, so a failed call still shows in the usage row
        result, trace = self._call_model(agent, system, messages)
        meter.add(result, trace, int((time.monotonic() - started) * 1000))
        out = result.structured if isinstance(result.structured, dict) else {}
        reply = out.get("reply") if isinstance(out.get("reply"), str) else ""
        operations = out.get("operations", [])
        meter.last_ops = operations if isinstance(operations, list) else []
        wanted = out.get("need_entities")
        if isinstance(wanted, list) and wanted:
            allowed = _lookup_ids(wanted, body.catalogue)
            if allowed:
                return ops_mod.Applied(draft=copy.deepcopy(body.draft), need_entities=allowed), ""
            return ops_mod.Applied(draft=copy.deepcopy(body.draft), problems=[
                {"path": "need_entities", "reason": "Those kinds of data are not available to this user."}]), ""
        applied = ops_mod.apply_operations(body.draft, operations)
        if not applied.problems and applied.question is None:
            applied.problems = self._validate(applied, body.catalogue)
        return applied, reply[:1000]

    def _call_model(self, agent: AiAgent, system: str, messages: List[Dict[str, Any]]):
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
        found = validate_against_catalogue(applied.draft, catalogue)
        if not CATALOGUE_CHECKS_TOUCHED_TILES_ONLY:
            return found
        touched = {i for i, t in enumerate(applied.draft["tiles"]) if t.get("id") in set(applied.changed_tile_ids)}
        return [p for p in found if any(p["path"].startswith(f"tiles[{i}]") for i in touched)]

    def _log(self, body: schemas.TurnRequest, agent: AiAgent, meter: "_Meter", image_count: int) -> None:
        if meter.calls == 0:
            return
        repo = UsageRepository(self.db, self.key.tenant_id, self.key.product)
        model = meter.model or agent.model or ""
        price = repo.price(model)
        cost = None
        if price is not None:  # raw tokens stay as measured; cost is derived from the price row
            cost = (Decimal(meter.tokens_in) * price.input_per_mtok + Decimal(meter.tokens_out) * price.output_per_mtok) / Decimal(1_000_000)
        repo.add(DashUsage(
            feature=FEATURE, cost_usd=cost, dashboard_id=body.dashboard_id, turn_id=body.turn_id, image_count=image_count, actor_ref=body.actor_ref,
            provider=meter.provider, model=model, tokens_in=meter.tokens_in,
            tokens_out=meter.tokens_out, latency_ms=meter.latency_ms, llm_calls=meter.calls, trace_id=meter.trace_id,
        ))


def _lookup_ids(wanted: List[Any], catalogue: Dict[str, Any]) -> List[str]:
    """The ids the model asked for that the viewer may read (in ``index``) and that are not already sent in full."""
    indexed = {i.get("entity") for i in catalogue.get("index") or [] if isinstance(i, dict)}
    have = {e.get("entity") for e in catalogue.get("entities") or [] if isinstance(e, dict)}
    seen: List[str] = []
    for e in wanted:
        if isinstance(e, str) and e in indexed and e not in have and e not in seen:
            seen.append(e)
    return seen


def _images_invalid(message: str) -> DashError:
    return DashError(422, "images_invalid", message)


def _check_images(images: List[Any]) -> List[Dict[str, str]]:
    """0-5 png / jpeg / webp images, each at most 5 MB decoded, 15 MB together. Never stored, never sniffed."""
    if len(images) > MAX_IMAGES:
        raise _images_invalid(f"Attach at most {MAX_IMAGES} images.")
    total = 0
    checked: List[Dict[str, str]] = []
    for item in images:
        if not isinstance(item, dict) or not isinstance(item.get("data_base64"), str) or not isinstance(item.get("media_type"), str):
            raise _images_invalid("One of the images could not be read.")
        if item["media_type"] not in IMAGE_TYPES:
            raise _images_invalid("Images must be PNG, JPEG or WebP.")
        if len(item["data_base64"]) > MAX_IMAGE_BASE64_CHARS:  # refuse before decoding anything that big
            raise _images_invalid("Each image must be 5 MB or smaller.")
        try:
            size = len(base64.b64decode(item["data_base64"], validate=True))
        except (binascii.Error, ValueError):
            raise _images_invalid("One of the images could not be read.")
        if size > MAX_IMAGE_BYTES:
            raise _images_invalid("Each image must be 5 MB or smaller.")
        total += size
        checked.append({"media_type": item["media_type"], "data_base64": item["data_base64"]})
    if total > MAX_IMAGES_TOTAL_BYTES:
        raise _images_invalid("The images together must be 15 MB or smaller.")
    return checked


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
        self.tokens_in += int(result.tokens_in or 0)
        self.tokens_out += int(result.tokens_out or 0)
        self.latency_ms += latency_ms
        self.model = result.model or self.model
        self.provider = getattr(trace, "provider", None) or self.provider
        self.trace_id = getattr(trace, "id", None) or self.trace_id

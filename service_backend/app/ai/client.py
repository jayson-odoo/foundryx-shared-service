"""The one seam every AI consumer in the platform calls (plan §7).

`AiClient.complete(...)` resolves the credential, picks the provider (or the
stub), runs the call, writes the trace + spans, and returns a normalized
`LLMResult`. Callers never touch a vendor SDK, never branch on provider and
never see an API key.

**Key resolution (AC-BI-11, Bi-D18)** mirrors SMTP/storage: an agent uses its
OWN `connection_id`; the "is any LLM configured at all?" prerequisite probe
falls back tenant → platform. Because `type='llm'` is carved out of the
one-per-type index (Bi-D21), that probe must tolerate SEVERAL rows and pick
DETERMINISTICALLY - tenant rows before platform, then oldest active first.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.ai.stub import is_dev, stub_provider, STUB_PROVIDER
from app.ai.tracing import TraceWriter, llm_span_payload
from app.integrations import get_provider
from app.integrations.base import LLMError, LLMResult
from app.models.ai import (
    SPAN_KIND_LLM_CALL,
    TRACE_STATUS_ERROR,
    TRACE_STATUS_OK,
    AiAgent,
    AiTrace,
)
from app.models.connection import CONNECTION_STATUS_ERROR, Connection
from app.models.tenant import PLATFORM_TENANT_ID
from app.secrets import decrypt_secret

logger = logging.getLogger(__name__)

LLM_TYPE = "llm"


@dataclass
class ResolvedConnection:
    """A usable LLM credential, or the signal that we're running stubbed."""

    connection: Optional[Connection]
    credentials: Dict[str, Any]
    provider_key: str
    is_stub: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decrypt(connection: Connection) -> Dict[str, Any]:
    if not connection.credentials_json:
        return {}
    try:
        return decrypt_secret(connection.credentials_json)
    except InvalidToken:
        # A rotated FERNET_KEY must not 500 - surface it as a clean prerequisite
        # failure the operator can act on.
        raise LLMError(
            "Stored credentials for this AI connection can no longer be decrypted "
            "- re-enter the API key on the connection and save."
        ) from None


def any_llm_connection(db: Session, tenant_id: str) -> Optional[Connection]:
    """The prerequisite probe (AC-BI-11): does this tenant have ANY usable LLM
    connection - its own, else the platform's?

    Deliberately NOT `resolve_for_type`: with the `llm` carve-out a tenant may
    hold several rows, so this orders explicitly (oldest active first) to stay
    deterministic across calls. ERROR rows are skipped, matching every other
    resolver in the codebase.
    """

    def _pick(owner_id: str) -> Optional[Connection]:
        return (
            db.query(Connection)
            .filter(
                Connection.tenant_id == owner_id,
                Connection.type == LLM_TYPE,
                Connection.is_active.is_(True),
                Connection.status != CONNECTION_STATUS_ERROR,
            )
            .order_by(Connection.created_at.asc(), Connection.id.asc())
            .first()
        )

    own = _pick(tenant_id)
    if own is not None:
        return own
    if tenant_id != PLATFORM_TENANT_ID:
        return _pick(PLATFORM_TENANT_ID)
    return None


def resolve_for_agent(db: Session, tenant_id: str, agent: AiAgent) -> ResolvedConnection:
    """An agent resolves by its OWN `connection_id` (Bi-D21), tenant-scoped.

    A missing/cross-tenant/inactive connection falls through to the stub only
    when nothing else is configured either; otherwise it raises so the failure
    is loud rather than silently answering with canned text in production.
    """
    connection: Optional[Connection] = None
    if agent.connection_id:
        connection = (
            db.query(Connection)
            .filter(
                Connection.id == agent.connection_id,
                # Tenant-scope a STORED id at USE time - the polymorphic
                # target_id rule (defense in depth even though the write path
                # validates it). The platform tenant's row is a legal fallback
                # target, so it is accepted explicitly.
                Connection.tenant_id.in_([tenant_id, PLATFORM_TENANT_ID]),
            )
            .first()
        )

    if connection is None:
        # No usable connection on the agent - is anything configured at all?
        if any_llm_connection(db, tenant_id) is None:
            return ResolvedConnection(None, {}, STUB_PROVIDER, is_stub=True)
        raise LLMError(
            "This agent's AI connection is missing or was removed - pick another "
            "connection on the agent."
        )

    credentials = _decrypt(connection)
    if is_dev(credentials, has_connection=True):
        return ResolvedConnection(connection, credentials, STUB_PROVIDER, is_stub=True)
    return ResolvedConnection(connection, credentials, connection.provider, is_stub=False)


class AiClient:
    """Run a completion for an agent, traced end to end."""

    def __init__(self, db: Session):
        self.db = db

    def complete(
        self,
        *,
        tenant_id: str,
        agent: AiAgent,
        system: str,
        messages: List[Dict[str, str]],
        output_schema: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        skill_key: Optional[str] = None,
        prompt_version: Optional[int] = None,
        actor_id: Optional[str] = None,
    ) -> Tuple[LLMResult, AiTrace]:
        """One traced completion. Raises `LLMError` on failure - but the trace
        is written FIRST (status='error'), so a failed run is still observable.
        """
        if not agent.is_enabled:
            raise LLMError(f'The agent "{agent.name}" is disabled.')

        resolved = resolve_for_agent(self.db, tenant_id, agent)
        provider_key = resolved.provider_key

        if resolved.is_stub:
            provider = stub_provider
        else:
            provider = get_provider(provider_key)
            if provider is None or getattr(provider, "type", "") != LLM_TYPE:
                raise LLMError(
                    f'The AI connection uses an unknown provider "{provider_key}".'
                )

        model = agent.model or ""
        writer = TraceWriter(
            self.db,
            tenant_id=tenant_id,
            agent_id=agent.id,
            agent_name=agent.name,
            conversation_id=conversation_id,
            skill_key=skill_key,
            prompt_version=prompt_version,
            provider=provider_key,
            model=model,
            created_by=actor_id,
        )

        started = _now()
        config = dict(resolved.connection.config_json or {}) if resolved.connection else {}
        try:
            result = provider.complete(
                config,
                resolved.credentials,
                model=model,
                system=system,
                messages=messages,
                output_schema=output_schema,
                temperature=agent.temperature or 0.0,
            )
        except LLMError as exc:
            writer.add_span(
                span_kind=SPAN_KIND_LLM_CALL,
                name="completion",
                input_json=llm_span_payload(
                    system=system, messages=messages, output_schema=output_schema
                ),
                latency_ms=_elapsed_ms(started),
                status=TRACE_STATUS_ERROR,
                error=str(exc),
                started_at=started,
            )
            writer.finish(status=TRACE_STATUS_ERROR, error=str(exc))
            raise

        writer.add_span(
            span_kind=SPAN_KIND_LLM_CALL,
            name="completion",
            input_json=llm_span_payload(
                system=system, messages=messages, output_schema=output_schema
            ),
            output_json={"text": result.text, "structured": result.structured},
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=_elapsed_ms(started),
            status=TRACE_STATUS_OK,
            started_at=started,
        )
        trace = writer.finish(status=TRACE_STATUS_OK)
        return result, trace


def _elapsed_ms(since: datetime) -> int:
    return int((_now() - since).total_seconds() * 1000)

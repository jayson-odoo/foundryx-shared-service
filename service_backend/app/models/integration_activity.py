"""Integration activity log (sprint-4/12, Developer Logs console) — core
``public`` table. ONE generic, source-tagged row per integration interaction so
a future consumable service (storage, LLM) writes to the SAME console via the
generic ``ActivityLogService`` seam — not an omnichannel-scoped table.

Slice 1 writes the ``inbound_api`` source (public gateway request logging);
``outbound_meta`` / ``embed_session`` land in later slices, and
``webhook_delivery`` is merged READ-ONLY from ``webhook_deliveries`` (its own
source of truth) — the enum value exists so the console treats every leg
uniformly.

Every query is tenant-scoped. Datetimes are ``UTCDateTime`` (never plain
``DateTime``). JSON columns are ``JSON(none_as_null=True)`` (a cleared column is
SQL NULL, not JSON ``'null'`` — house gotcha).
"""
import uuid

from sqlalchemy import Column, Index, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.database import Base
from app.models.utc_datetime import UTCDateTime

_JSON = GenericJSON(none_as_null=True)

# Source of the activity row (code branches on these; the console badges them).
SOURCE_INBOUND_API = "inbound_api"
SOURCE_EMBED_SESSION = "embed_session"
SOURCE_OUTBOUND_META = "outbound_meta"
SOURCE_WEBHOOK_DELIVERY = "webhook_delivery"
# Outbound calls the ``autocount`` module makes to a customer's on-prem
# AutoCount instance (sprint-4/13). ``ACTIVITY_SOURCES`` is a CLOSED tuple —
# without this value the ESB's calls never render in the Developer Logs console.
SOURCE_AUTOCOUNT = "autocount"
# Calendar reads the ``meetings`` module makes against Google (sprint-5 S0).
# Same reason as ``autocount`` above: the tuple is CLOSED, so a missing value
# means the module's runs never render in the Developer Logs console.
SOURCE_MEETINGS = "meetings"

ACTIVITY_SOURCES = (
    SOURCE_INBOUND_API,
    SOURCE_EMBED_SESSION,
    SOURCE_OUTBOUND_META,
    SOURCE_WEBHOOK_DELIVERY,
    SOURCE_AUTOCOUNT,
    SOURCE_MEETINGS,
)

# Outcome — code branches on these; the console filters/segments by them.
ACTIVITY_SUCCESS = "success"
ACTIVITY_ERROR = "error"
ACTIVITY_PENDING = "pending"

ACTIVITY_STATUSES = (ACTIVITY_SUCCESS, ACTIVITY_ERROR, ACTIVITY_PENDING)


def _uuid() -> str:
    return str(uuid.uuid4())


class IntegrationActivity(Base):
    __tablename__ = "integration_activity"
    __table_args__ = (
        Index("ix_integration_activity_tenant_created", "tenant_id", "created_at"),
        Index("ix_integration_activity_tenant_trace", "tenant_id", "trace_id"),
        Index("ix_integration_activity_tenant_source", "tenant_id", "source"),
        Index("ix_integration_activity_tenant_status", "tenant_id", "status"),
        Index("ix_integration_activity_tenant_extref", "tenant_id", "external_ref"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    # Attribution — every query tenant-scoped. NOT NULL: a row we cannot
    # attribute to a tenant is never written (an unauthenticated 401 with no
    # resolvable key is skipped, not stored — no console could ever show it).
    tenant_id = Column(String, nullable=False, index=True)
    # Correlation id minted at the inbound gateway; threaded to the outbound leg
    # (Slice 2). NULL for a standalone row.
    trace_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=False)  # one of ACTIVITY_SOURCES
    workspace_id = Column(String, nullable=True, index=True)
    api_key_id = Column(String, nullable=True)

    operation = Column(String, nullable=False)  # "POST /messages", "graph:send", …
    method = Column(String, nullable=True)  # HTTP verb (inbound)
    status = Column(String, nullable=False)  # one of ACTIVITY_STATUSES
    status_code = Column(Integer, nullable=True)  # HTTP / Meta status
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)  # redacted
    latency_ms = Column(Integer, nullable=True)
    external_ref = Column(String, nullable=True)  # wamid / event_id (async join)

    request_summary_json = Column(_JSON, nullable=True)  # redacted metadata + body
    response_summary_json = Column(_JSON, nullable=True)  # redacted

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

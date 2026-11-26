"""Hub Connector models - all in ``app_hub_connector``.

Every table carries ``tenant_id`` as a plain indexed column (no cross-schema FK,
BL-030). Hub signing secrets and delivery bodies are Fernet-encrypted with core
``app/secrets.py``; CRM push keys are stored as a sha256 hash only.

A hub = a partner platform (first: EcoHub) that shows our availability to its
own customer companies. What each customer sees is decided HERE, per
(hub, customer company): locations, brands; the hub decides price exposure.
"""

from __future__ import annotations
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.models.utc_datetime import UTCDateTime

from .db import HubConnectorBase

_JSON = JSON(none_as_null=True)

DELIVERY_PENDING = "PENDING"
DELIVERY_SUCCESS = "SUCCESS"
DELIVERY_FAILED = "FAILED"


def _uuid() -> str:
    return str(uuid.uuid4())


def _created() -> Column:
    return Column(UTCDateTime(), server_default=func.now(), nullable=False)


def _updated() -> Column:
    return Column(UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)


class HcHub(HubConnectorBase):
    __tablename__ = "hc_hubs"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_hc_hubs_tenant_code"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(64), nullable=False)
    callback_url = Column(String(2000), nullable=True)
    secret_encrypted = Column(Text, nullable=False)
    # Owner ruling 26 Nov: price may sync to SS, but each hub has its own
    # expose switch, default OFF (EcoHub stays OFF).
    expose_price = Column(Boolean, nullable=False, default=False, server_default="false")
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_success_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()
    updated_at = _updated()


class HcHubCustomer(HubConnectorBase):
    """The transparency policy for ONE customer company on ONE hub."""

    __tablename__ = "hc_hub_customers"
    __table_args__ = (UniqueConstraint("hub_id", "customer_code", name="uq_hc_hub_customers_hub_customer"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    hub_id = Column(String, ForeignKey("hc_hubs.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_code = Column(String(64), nullable=False)
    location_codes_json = Column(_JSON, nullable=True)
    brand_codes_json = Column(_JSON, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = _created()
    updated_at = _updated()


class HcCustomer(HubConnectorBase):
    """Customer company catalogue pushed by the CRM (picker source)."""

    __tablename__ = "hc_customers"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_hc_customers_tenant_code"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    code = Column(String(64), nullable=False)
    name = Column(String(300), nullable=False)
    updated_at = _updated()


class HcItem(HubConnectorBase):
    """Latest availability facts for one item, as the CRM last pushed them.

    ``locations_json`` = ``[{code, name, onHand, reserved}]``;
    ``incoming_json`` = ``[{ref, locationCode|None, remaining}]`` (a line not yet
    allocated to a location has ``locationCode`` None).
    """

    __tablename__ = "hc_items"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_hc_items_tenant_code"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    code = Column(String(64), nullable=False)
    name = Column(String(300), nullable=False)
    brand_code = Column(String(64), nullable=True)
    brand_name = Column(String(200), nullable=True)
    price = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(8), nullable=True)
    locations_json = Column(_JSON, nullable=True)
    incoming_json = Column(_JSON, nullable=True)
    updated_at = _updated()


class HcSentView(HubConnectorBase):
    """The last view of an item delivered to a hub customer (only changes go out)."""

    __tablename__ = "hc_sent_views"
    __table_args__ = (UniqueConstraint("hub_customer_id", "item_code", name="uq_hc_sent_views_customer_item"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    hub_customer_id = Column(
        String, ForeignKey("hc_hub_customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_code = Column(String(64), nullable=False)
    view_hash = Column(String(64), nullable=False)
    updated_at = _updated()


class HcApiKey(HubConnectorBase):
    __tablename__ = "hc_api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(200), nullable=False, default="")
    key_prefix = Column(String(16), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False)
    key_last4 = Column(String(4), nullable=False, default="")
    created_by = Column(String, nullable=True)
    created_at = _created()
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)


class HcDelivery(HubConnectorBase):
    __tablename__ = "hc_deliveries"
    __table_args__ = (Index("ix_hc_deliveries_due", "status", "next_at"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    hub_id = Column(String, ForeignKey("hc_hubs.id", ondelete="CASCADE"), nullable=False, index=True)
    hub_customer_id = Column(String, nullable=True)
    customer_code = Column(String(64), nullable=True)
    event = Column(String(32), nullable=False)
    body_encrypted = Column(Text, nullable=False)
    item_count = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=0)
    next_at = Column(UTCDateTime(), nullable=True)
    status = Column(String(16), nullable=False, default=DELIVERY_PENDING)
    last_code = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    last_attempt_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()

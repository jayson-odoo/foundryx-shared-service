"""Hub Connector module DB foundation - schema-isolated metadata
(``app_hub_connector``). Mirrors ``modules/lead_capture/db.py``."""

from __future__ import annotations
from sqlalchemy.orm import declarative_base

HUB_CONNECTOR_SCHEMA = "app_hub_connector"

HubConnectorBase = declarative_base()
HubConnectorBase.metadata.schema = HUB_CONNECTOR_SCHEMA

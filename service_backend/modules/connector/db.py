"""Connector module DB foundation - schema-isolated metadata (``app_connector``).

A separate declarative base keeps these tables out of core's ``Base.metadata``.
Mirrors ``modules/ideation/db.py``.
"""
from sqlalchemy.orm import declarative_base

CONNECTOR_SCHEMA = "app_connector"

ConnectorBase = declarative_base()
ConnectorBase.metadata.schema = CONNECTOR_SCHEMA

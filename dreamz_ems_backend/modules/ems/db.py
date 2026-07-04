"""EMS module DB foundation — schema-isolated metadata (``app_ems``).

Separate declarative base so the module's tables stay out of core's
``Base.metadata`` (core Alembic never sees them). Cross-schema FKs into core
(``tenants``, ``users``, ``statuses``) are referenced UNqualified so Postgres
resolves them via search_path and the SQLite test engine maps the schema away
(``schema_translate_map={EMS_SCHEMA: None}``).
"""
from sqlalchemy.orm import declarative_base

EMS_SCHEMA = "app_ems"

EmsBase = declarative_base()
EmsBase.metadata.schema = EMS_SCHEMA

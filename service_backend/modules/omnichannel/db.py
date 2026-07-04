"""Omnichannel module DB foundation — schema-isolated metadata.

Module tables live in their own Postgres schema (``app_omnichannel``), never in
core ``public`` (governance: DB = Schema-Isolated Relational Architecture). A
SEPARATE declarative base keeps these tables out of core's ``Base.metadata`` so
core Alembic autogenerate never sees them — the module owns its own lifecycle.

Cross-schema FKs into core tables (``users``, ``tenants``) are referenced
UNqualified so Postgres resolves them via search_path (public) and the SQLite
test engine — with ``schema_translate_map={OMNI_SCHEMA: None}`` — maps the
module schema away cleanly.
"""
from sqlalchemy.orm import declarative_base

OMNI_SCHEMA = "app_omnichannel"

# Separate metadata/base so the module is isolated from core migrations.
OmniBase = declarative_base()
OmniBase.metadata.schema = OMNI_SCHEMA

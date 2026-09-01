"""Ideation module DB foundation - schema-isolated metadata.

Module tables live in their own Postgres schema (``app_ideation``), never in core
``public`` (governance: DB = Schema-Isolated Relational Architecture). A SEPARATE
declarative base keeps these tables out of core's ``Base.metadata`` so core Alembic
autogenerate never sees them - the module owns its own lifecycle. Mirrors
``modules/omnichannel/db.py``.

Cross-schema FKs into core tables (``products``, ``statuses``, ``connections``)
and omnichannel tables (``contacts``) are referenced UNqualified so Postgres
resolves them via search_path (public) and the SQLite test engine - with
``schema_translate_map`` mapping the module schema onto an attached db - maps the
module schema away cleanly. (Cross-schema normal FKs are correct doctrine.)
"""
from sqlalchemy.orm import declarative_base

IDEATION_SCHEMA = "app_ideation"

# Separate metadata/base so the module is isolated from core migrations.
IdeationBase = declarative_base()
IdeationBase.metadata.schema = IDEATION_SCHEMA

"""Meetings module DB foundation - schema-isolated metadata.

Module tables live in their own Postgres schema (``app_meetings``), never in core
``public`` (governance: DB = Schema-Isolated Relational Architecture). A SEPARATE
declarative base keeps these tables out of core's ``Base.metadata`` so core Alembic
autogenerate never sees them - the module owns its own lifecycle. Mirrors
``modules/ideation/db.py``.

Refs to core rows (``tenants``, ``users``, ``files``, ``connections``) are PLAIN
INDEXED COLUMNS, not cross-schema FKs - the sanctioned simplest option
(PRINCIPLES: module governance). Nothing in this module joins another module.
"""
from sqlalchemy.orm import declarative_base

MEETINGS_SCHEMA = "app_meetings"

# Separate metadata/base so the module is isolated from core migrations.
MeetingsBase = declarative_base()
MeetingsBase.metadata.schema = MEETINGS_SCHEMA

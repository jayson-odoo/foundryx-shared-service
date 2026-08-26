"""AutoCount module DB foundation - schema-isolated metadata.

Module tables live in their own Postgres schema (``app_autocount``), never in
core ``public`` (governance: DB = Schema-Isolated Relational Architecture). A
SEPARATE declarative base keeps these tables out of core's ``Base.metadata`` so
core Alembic autogenerate never sees them - the module owns its own lifecycle.
Mirrors ``modules/ideation/db.py`` / ``modules/omnichannel/db.py``.

Cross-schema references into core tables (``connections``, ``tenants``,
``statuses``) are plain INDEXED COLUMNS, not DB-level FKs (BL-030) - a module
must never take a hard FK on core rows it does not own.

Every table in this schema carries BOTH ``tenant_id`` and ``company_id``; every
query filters both (AC-13-41). Cross-tenant OR cross-company leakage is a
critical defect.
"""
from sqlalchemy.orm import declarative_base

AUTOCOUNT_SCHEMA = "app_autocount"

# Separate metadata/base so the module is isolated from core migrations.
AutocountBase = declarative_base()
AutocountBase.metadata.schema = AUTOCOUNT_SCHEMA

"""Data backfills for `app_autocount`, kept OUT of the migration file on purpose.

    !!  MODULE ALEMBIC NEVER RUNS UNDER pytest.  !!

conftest builds the schema with ``create_all`` and ``run_module_migrations`` is a
Postgres-only no-op, so a migration's body is executed by exactly nothing in the
suite. A green run says nothing about it. Extracting the backfill into an
ordinary function means the LOGIC is testable directly (which is what actually
catches a wrong default), leaving only the DDL wrapper to be verified by review
plus a real ``alembic upgrade head`` against live Postgres.

Adding a column with a ``server_default`` populates existing rows on the ADD -
but the ADD only happens on a host where the column was missing. On a host where
``bootstrap_modules`` already ran ``install()``/``create_all`` FIRST, the column
arrives from the model with no server default, and the migration must not assume
it is populated. So the backfill is written to be correct in BOTH orders: it
fills only rows that lack a value, and is safe to run repeatedly.
"""
from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa

from .canonical.documents import is_document_entity
from .db import AUTOCOUNT_SCHEMA
from .envelopes import ENVELOPE_STATUS_DICT
from .mapping import SCOPE_LINE
from .models import AcEntityConfig, AcFieldMapping
from .sources import INITIAL_LOAD_WINDOWED

# Every entity config that predates this slice is a GRN one: a dict envelope with
# a lookback-windowed first read. Those were the only semantics available, so
# they are what those rows must end up with - stated as a backfill, not left to
# a column default that a create_all-first host would never apply.
_ENTITY_CONFIG_DEFAULTS = (
    ("envelope", ENVELOPE_STATUS_DICT),
    ("initial_load", INITIAL_LOAD_WINDOWED),
)


def default_schema(bind: Any) -> Optional[str]:
    """The schema to qualify with, for the engine actually in front of us.

    Postgres owns ``app_autocount``; SQLite (the test engine) has no schemas at
    all and a qualified name would be a syntax error.
    """
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    return AUTOCOUNT_SCHEMA if dialect == "postgresql" else None


def backfill_sink_impl_defaults(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Give every pre-existing ``ac_company`` row a ``sink_impl``. Returns the
    number of rows touched.

    Same two-order safety as ``backfill_entity_config_defaults``: a company that
    predates the sink columns must end up on the ``'logging'`` no-op (its
    behaviour before the column existed), stated as a backfill rather than left
    to a column default a create_all-first host would never apply. Fills only
    rows that lack a value and is safe to run repeatedly. Does **not** commit -
    the caller (Alembic's own connection, or ``update_tenant``) owns that.
    """
    prefix = f'"{schema}".' if schema else ""
    result = bind.execute(
        sa.text(
            f"UPDATE {prefix}ac_company SET sink_impl = 'logging' "
            f"WHERE sink_impl IS NULL OR sink_impl = ''"
        )
    )
    return result.rowcount or 0


def backfill_entity_config_defaults(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Give every pre-existing ``ac_entity_config`` row an envelope and an
    initial-load policy. Returns the number of rows touched.

    Does **not** commit: on the Alembic path this runs on the migration's own
    connection and must let Alembic's transaction own the commit (a
    ``db.commit()`` on ``op.get_bind()`` mid-migration corrupts the
    ``alembic_version`` stamp - learned on the storage-migration slice).

    ``schema=None`` for SQLite, which has no schemas.
    """
    prefix = f'"{schema}".' if schema else ""
    touched = 0
    for column, value in _ENTITY_CONFIG_DEFAULTS:
        # ``column`` comes from the fixed tuple above, never from input.
        result = bind.execute(
            sa.text(
                f"UPDATE {prefix}ac_entity_config SET {column} = :value "
                f"WHERE {column} IS NULL OR {column} = ''"
            ),
            {"value": value},
        )
        touched += result.rowcount or 0
    return touched


# Plan 22 (direct-DB ETL): the NOT NULL columns added to EXISTING tables and
# the value every pre-plan-22 row must end up with. Stated as a backfill, not
# left to a server default a create_all-first host would never apply.
_ETL_DEFAULTS = (
    ("ac_entity_config", "etl_status", "draft"),
    ("ac_staged_record", "op", "upsert"),
    ("ac_sync_run", "mode", "manual"),
    ("ac_sync_run", "rows_scanned", 0),
    ("ac_sync_run", "deleted_count", 0),
    # 0008 (plan 22 S2): hash-diff add/update counters on the run row.
    ("ac_sync_run", "added_count", 0),
    ("ac_sync_run", "updated_count", 0),
)


def backfill_etl_defaults(bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA) -> int:
    """Give every pre-plan-22 row its ETL defaults: a ``draft`` task status, an
    ``upsert`` staged op, a ``manual`` run mode with zero cost counters.
    Returns the number of rows touched.

    Same two-order safety as the backfills above: fills only rows that lack a
    value, safe to run repeatedly, does **not** commit (Alembic's connection or
    ``update_tenant`` owns that).
    """
    prefix = f'"{schema}".' if schema else ""
    touched = 0
    for table, column, value in _ETL_DEFAULTS:
        # ``table``/``column`` come from the fixed tuple above, never from input.
        blank = f" OR {column} = ''" if isinstance(value, str) else ""
        result = bind.execute(
            sa.text(
                f"UPDATE {prefix}{table} SET {column} = :value "
                f"WHERE {column} IS NULL{blank}"
            ),
            {"value": value},
        )
        touched += result.rowcount or 0
    return touched


# sprint-5/02 (AC-02-05): a document task's line fields used to be code-
# generated from three `source_config` picker columns (`lineKeyColumn`/
# `lineProductColumn`/`lineWarehouseColumn` - the now-deleted
# `mapping.document_line_rows`). This backfill converts an EXISTING task's
# pickers into three real, operator-editable `ac_field_mapping` rows and
# strips the keys, so the task behaves identically after upgrade with zero
# manual re-mapping.
#
#     !!  ORM-LEVEL, NOT RAW SQL (unlike the backfills above).  !!
# Unlike its siblings this one BUILDS ROWS (`AcFieldMapping`), not a column
# UPDATE - the natural unit is an ORM insert. A live-Postgres Alembic
# migration wraps this the SAME two-connection way every other backfill in
# this file does (a `Session(bind=op.get_bind())` reading/writing on a
# connection Alembic's own transaction will commit) - the module docstring's
# "test the FUNCTION directly" rule is why this is a plain function at all.
def backfill_document_line_mapping_pickers(
    db: Any, tenant_id: str, company_id: str, entity_type: str
) -> int:
    """Idempotent per (tenant, company, entity): a second call is a no-op
    (returns 0) once ANY line row exists for it - whether created by THIS
    backfill or by an operator who has since mapped lines by hand. Returns
    the number of line rows created (0-3)."""
    if not is_document_entity(entity_type):
        return 0
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == tenant_id,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == entity_type,
        )
        .one_or_none()
    )
    if config is None:
        return 0

    source_config = dict(config.source_config or {})
    line_key_column = str(source_config.get("lineKeyColumn") or "").strip()
    line_product_column = str(source_config.get("lineProductColumn") or "").strip()
    line_warehouse_column = str(source_config.get("lineWarehouseColumn") or "").strip()

    already_has_lines = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == tenant_id,
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_LINE,
        )
        .count()
        > 0
    )
    created = 0
    if not already_has_lines:
        order = 0
        if line_key_column:
            db.add(
                AcFieldMapping(
                    tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                    scope=SCOPE_LINE, source_path=line_key_column,
                    canonical_field="source_ref", transform="string",
                    is_required=True, is_enabled=True, sort_order=order,
                )
            )
            created += 1
            order += 1
        if line_product_column:
            db.add(
                AcFieldMapping(
                    tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                    scope=SCOPE_LINE, source_path=line_product_column,
                    canonical_field="product_ref", transform="ref_product",
                    is_required=True, is_enabled=True, sort_order=order,
                )
            )
            created += 1
            order += 1
        if line_warehouse_column:
            db.add(
                AcFieldMapping(
                    tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                    scope=SCOPE_LINE, source_path=line_warehouse_column,
                    canonical_field="warehouse_ref", transform="ref_warehouse",
                    is_required=False, is_enabled=True, sort_order=order,
                )
            )
            created += 1
            order += 1

    # Strip the picker keys EVERY call (idempotent w.r.t. the config half
    # too, independent of whether rows were just created) - a JSON column
    # needs a FRESH dict reassigned, never an in-place mutation of the
    # existing one, or SQLAlchemy misses the change (the house gotcha).
    stripped = {
        k: v for k, v in source_config.items()
        if k not in ("lineKeyColumn", "lineProductColumn", "lineWarehouseColumn")
    }
    if stripped != source_config:
        config.source_config = stripped

    db.flush()
    return created

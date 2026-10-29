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

Every helper runs at ANY module stamp (its migration's own, or HEAD via
``update_tenant``) and checks ``existing_columns`` first - the 2026-09-06
incident and the rule live there and in
``documentation/engineering/storage-and-background-jobs.md``.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import sqlalchemy as sa

from .canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    is_document_entity,
)
from .canonical.masters import ENTITY_CUSTOMER, ENTITY_PRODUCT
from .db import AUTOCOUNT_SCHEMA
from .envelopes import ENVELOPE_STATUS_DICT
from .mapping import DOCUMENT_LINE_FIXED_FIELDS, SCOPE_HEADER, SCOPE_LINE
from .models import (
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_AUTOCOUNT_READ,
    AcEntityConfig,
    AcFieldMapping,
)
from .sources import INITIAL_LOAD_WINDOWED

logger = logging.getLogger("foundryx.autocount")

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

def existing_columns(
    bind: Any, table: str, *, schema: Optional[str]
) -> Optional[frozenset[str]]:
    """The columns ``table`` actually has on the live connection, or ``None``
    when the table does not exist yet.

    A backfill runs at ANY stamp (its migration's own down_revision, or HEAD
    via ``update_tenant``), so it must ask the connection what is there -
    never the ORM model, which always reflects code HEAD. Incident and rule:
    ``documentation/engineering/storage-and-background-jobs.md`` (2026-09-06).

    A ``Session`` is unwrapped to ``session.connection()``, NOT ``get_bind()``:
    inspecting the engine checks out a SECOND pooled connection, blind to the
    session's uncommitted work, and under StaticPool SQLite its return to the
    pool rolls the session's pending writes back.

    ``schema=None`` (SQLite tests) also searches the attached schemas:
    conftest puts the module tables in an attached database via
    ``schema_translate_map`` and ``has_table(schema=None)`` looks at ``main``
    only. Postgres callers always pass ``app_autocount``.
    """
    connectable = bind.connection() if hasattr(bind, "get_bind") else bind
    inspector = sa.inspect(connectable)
    if inspector.has_table(table, schema=schema):
        return frozenset(col["name"] for col in inspector.get_columns(table, schema=schema))
    if schema is not None:
        return None
    for candidate in inspector.get_schema_names():
        if candidate in (None, "main"):
            continue
        if inspector.has_table(table, schema=candidate):
            return frozenset(
                col["name"] for col in inspector.get_columns(table, schema=candidate)
            )
    return None


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

    Schema-tolerant (prod incident, 2026-09-06 - see ``existing_columns``): a
    stamp before the table/column existed is a silent no-op here, never an
    ``UndefinedColumn``/``UndefinedTable``, so this function is safe to call
    from ANY migration in the chain, not only the one that first needed it.
    """
    columns = existing_columns(bind, "ac_company", schema=schema)
    if columns is None or "sink_impl" not in columns:
        return 0
    prefix = f'"{schema}".' if schema else ""
    result = bind.execute(
        sa.text(
            f"UPDATE {prefix}ac_company SET sink_impl = 'logging' "
            f"WHERE sink_impl IS NULL OR sink_impl = ''"
        )
    )
    return result.rowcount or 0


def backfill_delivery_mode_defaults(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Give every pre-existing ``ac_entity_config`` row a ``delivery_mode``
    (sprint-5/10, AC-10-10). Returns the number of rows touched.

    Same contract as ``backfill_sink_impl_defaults`` (see its own docstring):
    an entity config that predates the column must land on ``'push'`` -
    today's behaviour before this plan existed. Fills only NULL/blank rows
    and is safe to run repeatedly; does **not** commit - the caller
    (Alembic's own connection, or ``update_tenant``) owns that.
    """
    columns = existing_columns(bind, "ac_entity_config", schema=schema)
    if columns is None or "delivery_mode" not in columns:
        return 0
    prefix = f'"{schema}".' if schema else ""
    result = bind.execute(
        sa.text(
            f"UPDATE {prefix}ac_entity_config SET delivery_mode = 'push' "
            f"WHERE delivery_mode IS NULL OR delivery_mode = ''"
        )
    )
    return result.rowcount or 0


def backfill_disable_credit_limit_mapping_rows(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Disable every ENABLED ``customer`` ``ac_field_mapping`` row that targets
    ``credit_limit``. Returns the number of rows touched.

    Sorento contract 2.1 (sprint-5/04): ``CanonicalCustomer.SINK_FIELDS`` no
    longer carries ``credit_limit`` - Sorento's ``CanonicalCustomer`` on
    ``feat/ingest-parity`` (their PR #699) sets ``extra="forbid"`` and does
    not declare the field, so a payload naming it is a field-named 422. The
    drill that found it ran against Sorento's LOCAL ingest-parity lane
    (:8042, build b1c01aa2f, ``extra="forbid"``), NOT Sorento main: 27/27 SIM
    customers failed there. A tenant's already-saved enabled row that still
    targets ``credit_limit`` is a DEAD row after that change: mapped, never
    sent (``sink_payload`` only emits ``SINK_FIELDS``), invisible in the
    editor (the target left the accepted set, so the picker no longer offers
    it) and pruned by ``delete_unknown`` on the next save. It does NOT trip
    the mapping PUT guard - the guard validates only the targets the editor
    submits, and the editor never submits a target it cannot show. The real
    benefit of this sweep is narrower and still worth having: the stored
    mapping table matches the accepted target set for every tenant WITHOUT
    waiting for each operator's next save, and the App Store 0.4.0 -> 0.5.0
    bump carries a visible, delivered change rather than a silent one.

    ``entity_type = 'customer'`` only: the canonical name ``credit_limit``
    is customer-specific today, but the sweep must never reach a row of
    another entity that happens to share the name later. Idempotent (fills
    only rows still ``is_enabled``), across ALL tenants/companies, does
    **not** commit (Alembic's connection or ``update_tenant`` owns that).

    Runs at ANY module stamp (module Alembic 0013 and ``update_tenant`` both
    call it), so it checks what the live table actually has first - see
    ``existing_columns`` - and is a no-op on a schema that does not carry
    ``ac_field_mapping`` with ``is_enabled``/``entity_type``/``canonical_field``
    yet.
    """
    columns = existing_columns(bind, "ac_field_mapping", schema=schema)
    if columns is None or not {"is_enabled", "entity_type", "canonical_field"} <= columns:
        return 0
    prefix = f'"{schema}".' if schema else ""
    result = bind.execute(
        sa.text(
            f"UPDATE {prefix}ac_field_mapping SET is_enabled = :disabled "
            f"WHERE canonical_field = :field AND entity_type = :entity_type "
            f"AND is_enabled = :enabled"
        ),
        {
            "disabled": False,
            "field": "credit_limit",
            "entity_type": "customer",
            "enabled": True,
        },
    )
    return result.rowcount or 0


def backfill_db_company_entity_sources(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Repair a DATABASE company's stranded, never-run ``autocount_read``
    entity configs: flip them to ``sql_db``, except ``goods_received_note``,
    which is DELETED (config + its ``ac_field_mapping`` rows). Returns the
    number of rows repaired (flipped + deleted configs).

    Prod incident 2026-09-06: ``seed_company_defaults`` seeded the vendor-API
    entity set onto EVERY company on the App Store Update reseed, so a company
    whose source connection is the ``sql_database`` provider got API-sourced
    Customer/Supplier/GRN rows, and the entities list (which hid "Change
    source" on a DB company, AC-01-18) left no UI way out. The seed now stops
    at a DB company (D13: born empty); this sweep repairs what it already
    produced, on the SAME predicate for both actions - a DB company's config
    still at ``autocount_read`` that has NEVER RUN (``last_run_at IS NULL``
    and no ``ac_watermark`` row carrying a ``last_modified_at``, the
    pipeline's own "has run" markers):

    * supplier / customer (any entity with a database task) -> ``sql_db``;
    * ``goods_received_note`` -> DELETED, mapping rows first, because GRN has
      NO database task at all (``update_task`` answers "not available on a
      database company", so a flipped GRN row would only show a dead
      Configure control the operator can never use).

    A row with any run history is left to the operator, who can now reach
    "Change source" on it. Idempotent; across ALL tenants/companies; does
    **not** commit.

    The company's provider comes from core ``connections`` - a READ-ONLY,
    tenant-matched join (``cn.tenant_id = co.tenant_id``, never a bare id
    lookup). The module never alters a core table; a SELECT against one is
    fine. Only the MODULE tables are schema-qualified: core ``connections``
    resolves through the search path on Postgres and lives in ``main`` on the
    SQLite test rig, so it stays unqualified on both.

    Runs at ANY module stamp (module Alembic 0014 and ``update_tenant`` both
    call it), so every table/column it names is checked on the live
    connection first (``existing_columns``) and it degrades to a no-op.
    """
    needed = {
        "ac_entity_config": {"id", "tenant_id", "company_id", "entity_type", "source_impl", "last_run_at"},
        "ac_company": {"id", "tenant_id", "connection_id"},
        "ac_watermark": {"tenant_id", "company_id", "entity_type", "last_modified_at"},
        "ac_field_mapping": {"tenant_id", "company_id", "entity_type"},
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0
    core_have = existing_columns(bind, "connections", schema=None)
    if core_have is None or not {"id", "tenant_id", "provider"} <= core_have:
        return 0
    prefix = f'"{schema}".' if schema else ""

    # The shared predicate over an ``ac_entity_config`` row aliased ``c``:
    # never-run, still API-sourced, on a company whose source connection is
    # the sql_database provider (tenant-matched at every hop).
    stranded = (
        "c.source_impl = :api "
        "AND c.last_run_at IS NULL "
        "AND c.company_id IN ("
        f"  SELECT co.id FROM {prefix}ac_company co "
        "  JOIN connections cn "
        "    ON cn.id = co.connection_id AND cn.tenant_id = co.tenant_id "
        "  WHERE cn.provider = :provider AND co.tenant_id = c.tenant_id"
        ") "
        "AND NOT EXISTS ("
        f"  SELECT 1 FROM {prefix}ac_watermark w "
        "  WHERE w.tenant_id = c.tenant_id "
        "    AND w.company_id = c.company_id "
        "    AND w.entity_type = c.entity_type "
        "    AND w.last_modified_at IS NOT NULL"
        ")"
    )
    params = {"api": "autocount_read", "provider": "sql_database", "grn": "goods_received_note"}

    # 1) GRN: mapping rows first (no FK to lean on), then the config itself.
    bind.execute(
        sa.text(
            f"DELETE FROM {prefix}ac_field_mapping "
            f"WHERE entity_type = :grn AND EXISTS ("
            f"  SELECT 1 FROM {prefix}ac_entity_config c "
            f"  WHERE c.entity_type = :grn "
            f"    AND c.tenant_id = {prefix}ac_field_mapping.tenant_id "
            f"    AND c.company_id = {prefix}ac_field_mapping.company_id "
            f"    AND {stranded}"
            f")"
        ),
        params,
    )
    deleted = bind.execute(
        sa.text(
            f"DELETE FROM {prefix}ac_entity_config "
            f"WHERE entity_type = :grn AND id IN ("
            f"  SELECT c.id FROM {prefix}ac_entity_config c WHERE c.entity_type = :grn AND {stranded}"
            f")"
        ),
        params,
    ).rowcount or 0

    # 2) Everything else: point it at the database task it should have had.
    flipped = bind.execute(
        sa.text(
            f"UPDATE {prefix}ac_entity_config SET source_impl = :sql_db "
            f"WHERE entity_type <> :grn AND id IN ("
            f"  SELECT c.id FROM {prefix}ac_entity_config c WHERE c.entity_type <> :grn AND {stranded}"
            f")"
        ),
        {**params, "sql_db": "sql_db"},
    ).rowcount or 0
    return flipped + deleted


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

    Schema-tolerant (prod incident, 2026-09-06 - see ``existing_columns``):
    a stamp before ``ac_entity_config`` (or one of its two columns) existed
    skips that column rather than raising, so this is safe at ANY stamp.
    """
    columns = existing_columns(bind, "ac_entity_config", schema=schema)
    if columns is None:
        return 0
    prefix = f'"{schema}".' if schema else ""
    touched = 0
    for column, value in _ENTITY_CONFIG_DEFAULTS:
        if column not in columns:
            continue
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

    Schema-tolerant (prod incident, 2026-09-06 - see ``existing_columns``):
    ``_ETL_DEFAULTS`` spans THREE tables across TWO migrations (0007's own
    columns and 0008's ``added_count``/``updated_count``), so a stamp
    between them - or before any of them - must skip whichever entries name
    a table/column that is not there YET, never fail the whole backfill.
    Columns are inspected ONCE per table (several entries share
    ``ac_sync_run``), not once per entry.
    """
    prefix = f'"{schema}".' if schema else ""
    touched = 0
    columns_by_table: Dict[str, Optional[frozenset]] = {}
    for table, column, value in _ETL_DEFAULTS:
        if table not in columns_by_table:
            columns_by_table[table] = existing_columns(bind, table, schema=schema)
        columns = columns_by_table[table]
        if columns is None or column not in columns:
            continue
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
# UPDATE - the natural unit is an ORM insert. The CONFIG read/write is
# COLUMN-ONLY (id/source_config/line_result_columns): migrations 0010-0012 call
# this at a stamp that predates `delivery_mode` (0020) / `preview_job_id`
# (0022), so a whole-model query would raise UndefinedColumn. The
# `AcFieldMapping` insert stays safe because every `ac_field_mapping` column
# already existed at 0005. A live-Postgres Alembic
# migration wraps this the SAME two-connection way every other backfill in
# this file does (a `Session(bind=op.get_bind())` reading/writing on a
# connection Alembic's own transaction will commit) - the module docstring's
# "test the FUNCTION directly" rule is why this is a plain function at all.
def backfill_document_line_mapping_pickers(
    db: Any, tenant_id: str, company_id: str, entity_type: str
) -> int:
    """Idempotent per (tenant, company, entity), and REPAIR-capable (review
    round B1): guard is PER CANONICAL FIELD, not "does any line row exist" -
    a task left with only the picker-derived rows (source_ref/product_ref/
    warehouse_ref, e.g. by an earlier run of this same backfill/migration
    0010) is missing its FIXED line fields (`mapping.DOCUMENT_LINE_FIXED_
    FIELDS` - qty_ordered, unit_price, … - the fields the now-deleted
    `document_line_rows` code-generated), which the old "any row exists"
    guard would have locked out of ever being repaired. Re-running this
    function always tops a task up to the FULL expected line set and never
    duplicates a field that is already there. Returns the number of line
    rows created (0 when the full set already exists)."""
    if not is_document_entity(entity_type):
        return 0
    # Column-only select, NOT the whole model: migrations 0010/0011/0012 run this at a
    # stamp that predates delivery_mode (0020) / preview_job_id (0022), so a whole-model
    # SELECT raises UndefinedColumn there. Column-only is safe at every stamp.
    config = (
        db.query(
            AcEntityConfig.id,
            AcEntityConfig.source_config,
            AcEntityConfig.line_result_columns,
        )
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

    existing_fields = {
        row.canonical_field
        for row in db.query(AcFieldMapping.canonical_field).filter(
            AcFieldMapping.tenant_id == tenant_id,
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_LINE,
        )
    }
    next_order = len(existing_fields)
    created = 0

    def _add(
        source_path: str, canonical_field: str, transform: str, required: bool,
        *, enabled: bool = True,
    ) -> None:
        nonlocal created, next_order
        if not source_path or canonical_field in existing_fields:
            return
        db.add(
            AcFieldMapping(
                tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                scope=SCOPE_LINE, source_path=source_path,
                canonical_field=canonical_field, transform=transform,
                is_required=required, is_enabled=enabled, sort_order=next_order,
            )
        )
        existing_fields.add(canonical_field)
        created += 1
        next_order += 1

    _add(line_key_column, "source_ref", "string", True)
    _add(line_product_column, "product_ref", "ref_product", True)
    _add(line_warehouse_column, "warehouse_ref", "ref_warehouse", False)

    #     !!  R1 (blocker, code-review round) - A FIXED FIELD ABSENT FROM
    #         THE PREVIEW SEEDS DISABLED.  !!
    # The FIXED column-name convention (source_path == canonical_field)
    # assumes the lineQuery returns a column literally spelled like the
    # canonical field - a real AutoCount column almost never is
    # (`DiscountAmt`, not `discount`). Seeding every fixed field ENABLED
    # regardless left the S1 preview-column gate rejecting the operator's
    # very first Mapping-tab save (live task 48e2b593 - "'discount' is not
    # among the line query's last preview columns"). A NEVER-previewed task
    # (`line_result_columns is None`) has nothing to check against yet, so
    # it stays permissive (enabled) - same "test first" convention as
    # `validate_source_config`'s `filterFormula` gate.
    line_columns = config.line_result_columns
    known_line_columns = frozenset(line_columns) if line_columns is not None else None
    for canonical_field, transform, required in DOCUMENT_LINE_FIXED_FIELDS.get(entity_type, ()):
        enabled = known_line_columns is None or canonical_field in known_line_columns
        _add(canonical_field, canonical_field, transform, required, enabled=enabled)

    # Strip the picker keys EVERY call (idempotent w.r.t. the config half
    # too, independent of whether rows were just created) - a JSON column
    # needs a FRESH dict reassigned, never an in-place mutation of the
    # existing one, or SQLAlchemy misses the change (the house gotcha).
    _strip_picker_keys_and_flush(db, config.id, source_config)
    return created


def _strip_picker_keys_and_flush(db: Any, config_id: Any, source_config: Dict[str, Any]) -> None:
    stripped = {
        k: v for k, v in source_config.items()
        if k not in ("lineKeyColumn", "lineProductColumn", "lineWarehouseColumn")
    }
    if stripped != source_config:
        # Column-only UPDATE of source_config alone (never loads the whole row).
        db.query(AcEntityConfig).filter(AcEntityConfig.id == config_id).update(
            {AcEntityConfig.source_config: stripped}, synchronize_session="evaluate"
        )

    db.flush()


def disable_line_rows_missing_from_preview(
    db: Any, tenant_id: str, company_id: str, entity_type: str
) -> int:
    """R1(c) repair (code-review round): flips an existing ENABLED line row
    whose ``source_path`` is not among the task's saved ``line_result_
    columns`` to ``is_enabled=False`` - the migration-0011 aftermath (a
    fixed field seeded enabled regardless of the preview, e.g. live task
    48e2b593) repaired in place, on the SAME "is this row's source_path
    real" question the S1 save-time gate asks. Idempotent (a second call
    touches nothing more); a NEVER-previewed task (``line_result_columns
    is None``) has nothing to check against yet and is left ENTIRELY
    alone - same "test first" convention as everywhere else in this file.
    Returns the number of rows disabled.
    """
    if not is_document_entity(entity_type):
        return 0
    # Column-only select, NOT the whole model: migrations 0010/0011/0012 run this at a
    # stamp that predates delivery_mode (0020) / preview_job_id (0022), so a whole-model
    # SELECT raises UndefinedColumn there. Column-only is safe at every stamp.
    config = (
        db.query(AcEntityConfig.id, AcEntityConfig.line_result_columns)
        .filter(
            AcEntityConfig.tenant_id == tenant_id,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == entity_type,
        )
        .one_or_none()
    )
    if config is None or config.line_result_columns is None:
        return 0

    known_line_columns = frozenset(config.line_result_columns)
    rows = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == tenant_id,
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_LINE,
            AcFieldMapping.is_enabled.is_(True),
        )
        .all()
    )
    touched = 0
    for row in rows:
        if row.source_path not in known_line_columns:
            row.is_enabled = False
            touched += 1
    db.flush()
    return touched


# feat/spo-container-number - Sorento holds 68,519 SPO allocations with no
# container: the SPO task's header query never selected AutoCount `PO.Ref`
# at all, on any tenant, so there was never a value to map. Two independent
# repairs per EXISTING `shipping_order` task, across ALL tenants:
#
# (a) add an enabled `Ref -> container_number` header mapping row when one
#     is not already there (an operator's own row - enabled, disabled, or
#     carrying a formula - is left exactly as they set it);
# (b) when the stored header query is BYTE-IDENTICAL to the OLD preset text
#     (with the task's OWN company's `database_name` substituted - the same
#     substitution `list_mapping_presets`'s "Use preset" picker performs),
#     replace it with the NEW preset text (selecting `h.Ref AS Ref`) and add
#     `"Ref"` to `result_columns` - the compared-column set a paged run's
#     change detection hashes derives from `result_columns` (minus the key
#     columns, `sql_source/source.py`), so without this the new column would
#     never enter the hash and a document whose only change is a newly
#     populated `Ref` would never re-stage.
#
# A query that is CUSTOMISED (including one that happens to match a SIBLING
# company's substitution - a picker copy-paste, not the preset) is left
# alone entirely and a WARNING names the config id, so an operator who wrote
# their own query keeps it and knows they need to add `Ref` by hand to pick
# up container numbers. (a) and (b) are independent: a customised query
# still gets the mapping row.
_OLD_PO_HEADER_QUERY_TEMPLATE = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)

_SHIPPING_ORDER_BACKFILL_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_config", "result_columns",
}
_SHIPPING_ORDER_BACKFILL_COMPANY_COLUMNS = {"id", "tenant_id", "database_name"}
_SHIPPING_ORDER_BACKFILL_FIELD_MAPPING_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "scope", "source_path",
    "canonical_field", "transform", "formula", "is_required", "is_enabled",
    "is_source_owned", "sort_order",
}


def backfill_shipping_order_container_number(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """(a) + (b) above, for every ``shipping_order`` ``ac_entity_config`` row
    across every tenant/company. Returns the number of individual changes
    made (mapping rows created + header queries replaced) - 0 on a schema
    that predates the tables/columns this touches (module Alembic 0016 and
    ``update_tenant`` both call it, so it must survive every stamp in the
    chain, not only the one it ships with).

    Called UNCONDITIONALLY on every ``update_tenant`` run, like every other
    backfill in this file - each check/write is idempotent (a mapping row
    already there is skipped, a query already at the NEW text is skipped
    silently), so re-running it costs a handful of no-op SELECTs, never a
    duplicate row or a repeat warning.

        !!  FROZEN ``sa.table`` ONLY - NEVER THE LIVE ORM MODEL.  !!
    A prior incident (module Alembic 0006, documented in
    ``documentation/engineering/storage-and-background-jobs.md``) queried
    the live ``AcCompany`` model from INSIDE a migration and raised
    ``UndefinedColumn`` on a fresh ``0001`` -> head replay once a LATER
    migration added a column the model had already grown to expect. This
    function is called from module Alembic 0016, so it selects/inserts/
    updates through frozen ``sa.table`` snapshots naming only the columns
    it actually touches (the ``_SHIPPING_ORDER_BACKFILL_*_COLUMNS`` sets
    below, already used for the existence check) - safe at ANY later stamp,
    no matter how many columns a future migration adds to these tables.

    Never a bare id lookup: a config's company is resolved WITH the config's
    OWN ``tenant_id`` (the polymorphic-target_id rule) before its
    ``database_name`` is trusted for the byte-identity check.
    """
    needed = {
        "ac_entity_config": _SHIPPING_ORDER_BACKFILL_ENTITY_CONFIG_COLUMNS,
        "ac_company": _SHIPPING_ORDER_BACKFILL_COMPANY_COLUMNS,
        "ac_field_mapping": _SHIPPING_ORDER_BACKFILL_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    from .presets import _PO_HEADER_QUERY

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    # Same unwrap ``existing_columns`` uses, and for the same reason - a
    # ``Session.get_bind()`` checks out a SECOND pooled connection, blind to
    # the session's own uncommitted work.
    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    configs = connectable.execute(
        sa.select(
            entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
            entity_config.c.source_config, entity_config.c.result_columns,
        ).where(entity_config.c.entity_type == ENTITY_SHIPPING_ORDER)
    ).fetchall()

    touched = 0
    for config_id, tenant_id, company_id, source_config, result_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]

        # (a) the mapping row, independent of the query check below.
        # Checked by `canonical_field` (the unique-constraint column), not
        # `source_path` - an operator's own row targeting `container_number`
        # from a different column still counts as "already there" and must
        # never collide with a second insert.
        has_ref_row = (
            connectable.execute(
                sa.select(field_mapping.c.id).where(
                    field_mapping.c.tenant_id == tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == ENTITY_SHIPPING_ORDER,
                    field_mapping.c.scope == SCOPE_HEADER,
                    field_mapping.c.canonical_field == "container_number",
                )
            ).first()
            is not None
        )
        if not has_ref_row:
            sort_order = connectable.execute(
                sa.select(sa.func.count())
                .select_from(field_mapping)
                .where(
                    field_mapping.c.tenant_id == tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == ENTITY_SHIPPING_ORDER,
                    field_mapping.c.scope == SCOPE_HEADER,
                )
            ).scalar() or 0
            connectable.execute(
                sa.insert(field_mapping).values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=ENTITY_SHIPPING_ORDER,
                    scope=SCOPE_HEADER,
                    source_path="Ref",
                    canonical_field="container_number",
                    transform="string",
                    formula=None,
                    is_required=False,
                    is_enabled=True,
                    # Not a NOT-NULL column DEFAULT at the database level
                    # (`AcFieldMapping.is_source_owned`'s `default=True` is
                    # ORM-side only) - a frozen `sa.table` insert must state
                    # it explicitly or a strict backend (SQLite) rejects the
                    # row outright.
                    is_source_owned=True,
                    sort_order=sort_order,
                )
            )
            touched += 1

        # (b) the header query, independent of (a) above.
        source_config = source_config or {}
        stored_query = source_config.get("query")
        old_text = _OLD_PO_HEADER_QUERY_TEMPLATE.replace("{database}", database_name)
        new_text = _PO_HEADER_QUERY.replace("{database}", database_name)
        if stored_query == old_text:
            fresh = dict(source_config)
            fresh["query"] = new_text
            columns_list = list(result_columns or [])
            if "Ref" not in columns_list:
                columns_list.append("Ref")
            connectable.execute(
                sa.update(entity_config)
                .where(entity_config.c.id == config_id)
                .values(source_config=fresh, result_columns=columns_list)
            )
            touched += 1
        elif stored_query != new_text:
            # Not the OLD preset (customised, or a sibling company's own
            # substitution pasted in) AND not already the NEW preset
            # (already migrated - silent, not a repeat warning every
            # `update_tenant` call): left untouched, named so an operator
            # can add `Ref` by hand.
            logger.warning(
                "Shipping-order task %s has a header query the "
                "container_number backfill does not recognise as the "
                "AutoCount SPO preset - left untouched. Add `Ref` to it "
                "to pick up container numbers.",
                config_id,
            )
    return touched


# ── sprint-5/07 - SO `Ref` (project label) ──────────────────────────────────

# The SO header query BEFORE this lane added `h.Ref AS Ref` - pinned VERBATIM
# (copied from `presets._SO_HEADER_QUERY` at the moment this lane started),
# independent of any later preset edit, same precedent as
# `_OLD_PO_HEADER_QUERY_TEMPLATE` above.
_OLD_SO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, "
    "h.SalesAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, "
    "h.Cancelled AS Cancelled, h.DebtorCode AS DebtorCode, "
    "h.DebtorName AS DebtorName, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
    "OUTER APPLY ("
    "SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, SUM(d.SubTotal) AS SubTotalSum, "
    "MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.SODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)

# The text 0019 rewrites a byte-identical OLD query TO - pinned FROZEN (it is
# the `presets._SO_HEADER_QUERY` text of sprint-5/07), never read off the live
# preset: once SS-SO-TRANSFERABLE moved the preset on, a live read would make
# 0019 jump a pre-`Ref` task straight to the newest text while appending only
# `Ref` to `result_columns`, and 0025 (which then sees its own target text)
# would skip it - stranding `Transferable` outside the row hash.
_REF_SO_HEADER_QUERY = _OLD_SO_HEADER_QUERY.replace(
    "h.Note AS Note, ", "h.Note AS Note, h.Ref AS Ref, ", 1
)

# SS-SO-TRANSFERABLE's own target text (0025) - FROZEN for the same reason:
# a later SO column must not let 0025 skip past it.
_TRANSFERABLE_SO_HEADER_QUERY = _REF_SO_HEADER_QUERY.replace(
    "h.Ref AS Ref, ", "h.Ref AS Ref, h.Transferable AS Transferable, ", 1
)

_SALES_ORDER_REF_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_config", "result_columns",
}
_SALES_ORDER_REF_COMPANY_COLUMNS = {"id", "tenant_id", "database_name"}
_SALES_ORDER_REF_FIELD_MAPPING_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "scope", "source_path",
    "canonical_field", "transform", "formula", "is_required", "is_enabled",
    "is_source_owned", "sort_order",
}


def backfill_sales_order_ref(bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA) -> int:
    """AC-07-07..11 - for every ``sales_order`` ``ac_entity_config`` row across
    every tenant/company: a query byte-identical to the OLD preset (its own
    company's ``database_name`` substituted) is swapped to the NEW preset
    text (``h.Ref AS Ref`` added) and ``"Ref"`` appended to
    ``result_columns``; a query already at the NEW text is skipped silently;
    anything else (a customised query, e.g. the production ``AED_SORENTO``
    shape) is left byte-untouched. A ``Ref -> ref`` header mapping row is
    created the moment none exists yet in ANY state (an operator's own row,
    enabled or disabled, is never duplicated or modified) - ENABLED when the
    query is the OLD/NEW preset text or already selects ``Ref``, DISABLED
    (with one WARNING naming the config id) otherwise, so no `ref` reaches
    the wire from a task an operator has not yet pointed at the column.

    Returns the number of individual changes made (mapping rows created +
    header queries replaced) - 0 (no error) against a schema that predates
    the tables/columns this touches. Module Alembic 0019 and ``update_tenant``
    both call this UNCONDITIONALLY, like every other backfill in this file -
    idempotent, safe to run repeatedly (0016/0018 precedent).

        !!  FROZEN ``sa.table`` ONLY - NEVER THE LIVE ORM MODEL.  !!
    See ``backfill_shipping_order_container_number`` above for the incident
    this rule comes from.

    Never a bare id lookup: a config's company is resolved WITH the config's
    OWN ``tenant_id`` (the polymorphic-target_id rule) before its
    ``database_name`` is trusted for the byte-identity check; a config whose
    company is missing under that tenant is skipped WITH a warning (never
    matched against another tenant's company of the same id).
    """
    needed = {
        "ac_entity_config": _SALES_ORDER_REF_ENTITY_CONFIG_COLUMNS,
        "ac_company": _SALES_ORDER_REF_COMPANY_COLUMNS,
        "ac_field_mapping": _SALES_ORDER_REF_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    # Same unwrap ``existing_columns`` uses, and for the same reason.
    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    configs = connectable.execute(
        sa.select(
            entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
            entity_config.c.source_config, entity_config.c.result_columns,
        ).where(entity_config.c.entity_type == ENTITY_SALES_ORDER)
    ).fetchall()

    touched = 0
    for config_id, tenant_id, company_id, source_config, result_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            logger.warning(
                "Sales-order task %s's company could not be resolved under "
                "its own tenant - the SO `Ref` backfill skipped it.",
                config_id,
            )
            continue
        database_name = company_row[0]

        has_ref_row = (
            connectable.execute(
                sa.select(field_mapping.c.id).where(
                    field_mapping.c.tenant_id == tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                    field_mapping.c.scope == SCOPE_HEADER,
                    field_mapping.c.canonical_field == "ref",
                )
            ).first()
            is not None
        )

        source_config = source_config or {}
        stored_query = source_config.get("query")
        columns_list = list(result_columns or [])
        old_text = _OLD_SO_HEADER_QUERY.replace("{database}", database_name)
        new_text = _REF_SO_HEADER_QUERY.replace("{database}", database_name)
        later_texts = {
            new_text,
            _TRANSFERABLE_SO_HEADER_QUERY.replace("{database}", database_name),
            # FULFIL-SO-REMARK: the FROZEN remark target is a later text too.
            _REMARK_SO_HEADER_QUERY.replace("{database}", database_name),
        }

        if stored_query in later_texts:
            # Already migrated (a previous pass, a later SO backfill, or a
            # freshly-created task already on a newer preset) - nothing to
            # do, no warning, and an operator's deliberately DELETED `ref`
            # row is never reseeded on the next `update_tenant`.
            continue

        query_replaced = False
        if stored_query == old_text:
            fresh = dict(source_config)
            fresh["query"] = new_text
            if "Ref" not in columns_list:
                columns_list.append("Ref")
            connectable.execute(
                sa.update(entity_config)
                .where(entity_config.c.id == config_id)
                .values(source_config=fresh, result_columns=columns_list)
            )
            touched += 1
            query_replaced = True

        if has_ref_row:
            # An operator's own row (or one this backfill already seeded on
            # an earlier pass) - never duplicated or modified, in ANY state.
            continue

        sort_order = connectable.execute(
            sa.select(sa.func.coalesce(sa.func.max(field_mapping.c.sort_order), -1) + 1)
            .where(
                field_mapping.c.tenant_id == tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                field_mapping.c.scope == SCOPE_HEADER,
            )
        ).scalar()
        enabled = query_replaced or "Ref" in columns_list
        connectable.execute(
            sa.insert(field_mapping).values(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                company_id=company_id,
                entity_type=ENTITY_SALES_ORDER,
                scope=SCOPE_HEADER,
                source_path="Ref",
                canonical_field="ref",
                transform="string",
                formula=None,
                is_required=False,
                is_enabled=enabled,
                is_source_owned=True,
                sort_order=sort_order,
            )
        )
        touched += 1
        if not enabled:
            logger.warning(
                "Sales-order task %s has a header query the `ref` backfill "
                "does not recognise as the AutoCount SO preset - left "
                "untouched. Add `h.Ref AS Ref` to the Query tab and enable "
                "the `Ref -> ref` row on the Mapping tab.",
                config_id,
            )
    return touched


# ── SS-SO-TRANSFERABLE - SO `Transferable` (partner of sorento #1421) ──────


def backfill_sales_order_transferable(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """The 0019 (`Ref`) repair, one column later: for every ``sales_order``
    ``ac_entity_config`` row across every tenant/company, a query byte-
    identical to the 0019 preset text (``_REF_SO_HEADER_QUERY``, own
    company's ``database_name`` substituted) is swapped to the FROZEN 0025
    text ``_TRANSFERABLE_SO_HEADER_QUERY`` (``h.Transferable AS Transferable``
    added after ``h.Ref AS Ref``) and ``"Transferable"`` appended to a
    non-empty ``result_columns``; a query already at that text is skipped
    silently (no row reseeded either); anything else (the production
    ``AED_SORENTO`` shape) is left byte-untouched. A ``Transferable ->
    transferable`` header row (``bool``, not required, source-owned, next
    ``sort_order``) is created the moment none exists in ANY state - ENABLED
    when the query was just rewritten or already selects ``Transferable``,
    DISABLED with one WARNING naming the config id otherwise.

    Returns the number of changes (rows created + queries replaced); 0 on a
    schema predating these tables. Module Alembic 0025 and ``update_tenant``
    both call it unconditionally - idempotent. Frozen ``sa.table`` only,
    never the live ORM model; company resolved WITH the config's own
    ``tenant_id`` (polymorphic-target_id rule) - see
    ``backfill_sales_order_ref`` for both rules' history.
    """
    needed = {
        "ac_entity_config": _SALES_ORDER_REF_ENTITY_CONFIG_COLUMNS,
        "ac_company": _SALES_ORDER_REF_COMPANY_COLUMNS,
        "ac_field_mapping": _SALES_ORDER_REF_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    configs = connectable.execute(
        sa.select(
            entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
            entity_config.c.source_config, entity_config.c.result_columns,
        ).where(entity_config.c.entity_type == ENTITY_SALES_ORDER)
    ).fetchall()

    touched = 0
    for config_id, tenant_id, company_id, source_config, result_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            logger.warning(
                "Sales-order task %s's company could not be resolved under "
                "its own tenant - the SO `Transferable` backfill skipped it.",
                config_id,
            )
            continue
        database_name = company_row[0]

        source_config = source_config or {}
        stored_query = source_config.get("query")
        columns_list = list(result_columns or [])
        old_text = _REF_SO_HEADER_QUERY.replace("{database}", database_name)
        new_text = _TRANSFERABLE_SO_HEADER_QUERY.replace("{database}", database_name)

        if stored_query == new_text or stored_query == _REMARK_SO_HEADER_QUERY.replace(
            "{database}", database_name
        ):
            # Already migrated (a previous pass, or a freshly-created task
            # already on the new preset, whose row `seed_company_defaults`
            # owns) - nothing to do, no warning, and an operator's
            # deliberately DELETED row is never reseeded.
            continue

        query_replaced = False
        if stored_query == old_text:
            fresh = dict(source_config)
            fresh["query"] = new_text
            values = {"source_config": fresh}
            # An EMPTY `result_columns` means "never previewed" - leave it
            # empty rather than caching a one-column list that would make the
            # watermark check fail with a misleading message.
            if columns_list and "Transferable" not in columns_list:
                columns_list.append("Transferable")
                values["result_columns"] = columns_list
            connectable.execute(
                sa.update(entity_config)
                .where(entity_config.c.id == config_id)
                .values(**values)
            )
            touched += 1
            query_replaced = True

        has_row = connectable.execute(
            sa.select(field_mapping.c.id).where(
                field_mapping.c.tenant_id == tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                field_mapping.c.scope == SCOPE_HEADER,
                field_mapping.c.canonical_field == "transferable",
            )
        ).first() is not None
        if has_row:
            # An operator's own row (or one an earlier pass seeded) - never
            # duplicated or modified, in ANY state.
            continue

        sort_order = connectable.execute(
            sa.select(sa.func.coalesce(sa.func.max(field_mapping.c.sort_order), -1) + 1)
            .where(
                field_mapping.c.tenant_id == tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                field_mapping.c.scope == SCOPE_HEADER,
            )
        ).scalar()
        enabled = query_replaced or "Transferable" in columns_list
        connectable.execute(
            sa.insert(field_mapping).values(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                company_id=company_id,
                entity_type=ENTITY_SALES_ORDER,
                scope=SCOPE_HEADER,
                source_path="Transferable",
                canonical_field="transferable",
                transform="bool",
                formula=None,
                is_required=False,
                is_enabled=enabled,
                is_source_owned=True,
                sort_order=sort_order,
            )
        )
        touched += 1
        if not enabled:
            logger.warning(
                "Sales-order task %s has a header query the `transferable` "
                "backfill does not recognise as the AutoCount SO preset - left "
                "untouched. Add `h.Transferable AS Transferable` to the Query "
                "tab and enable the `Transferable -> transferable` row on the "
                "Mapping tab.",
                config_id,
            )
    return touched


# ── FULFIL-SO-REMARK - SO `ShipInfo`, line `FurtherDescription`/`SectionHeading`

# The SO line preset text BEFORE this lane - FROZEN (never read off the live
# preset, same rule as the header texts above). The header's previous text is
# `_TRANSFERABLE_SO_HEADER_QUERY`.
_PRE_REMARK_SO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS DeliveryDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.SODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)

# FULFIL-SO-REMARK's own target texts (0032) - FROZEN, never read off the live
# preset, so a later SO preset lane cannot silently change what 0032 writes.
# `test_frozen_remark_targets_equal_todays_preset` forces a conscious re-pin.
_REMARK_SO_HEADER_QUERY = _TRANSFERABLE_SO_HEADER_QUERY.replace(
    "h.Transferable AS Transferable, ", "h.Transferable AS Transferable, h.ShipInfo AS ShipInfo, ", 1
)
_REMARK_SO_LINE_QUERY = _PRE_REMARK_SO_LINE_QUERY.replace(
    "d.Seq AS Seq ",
    "d.Seq AS Seq, d.FurtherDescription AS FurtherDescription, "
    "sh.SectionHeading AS SectionHeading ", 1,
).replace(
    "WHERE d.DocKey = :doc_key",
    "OUTER APPLY (SELECT TOP 1 x.Description AS SectionHeading "
    "FROM {database}.dbo.SODTL AS x WHERE x.DocKey = d.DocKey AND x.Seq < d.Seq "
    "AND (x.ItemCode IS NULL OR x.Qty IS NULL) "
    "AND LTRIM(RTRIM(ISNULL(x.Description, ''))) <> '' "
    "ORDER BY x.Seq DESC, x.DtlKey DESC) AS sh "
    "WHERE d.DocKey = :doc_key", 1,
)

_SO_REMARK_ENTITY_CONFIG_COLUMNS = _SALES_ORDER_REF_ENTITY_CONFIG_COLUMNS | {"line_result_columns"}


def backfill_so_remark_fields(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA, tenant_id: Optional[str] = None,
) -> int:
    """Bring every ``sales_order`` task onto the FULFIL-SO-REMARK preset: a
    header ``ShipInfo -> ship_info`` row and line ``FurtherDescription ->
    line_remark`` / ``SectionHeading -> section_heading`` rows.

    Per task, the header and the line sides are independent and idempotent:

    * a stored query byte-identical to the FROZEN previous preset text (own
      company's ``database_name`` substituted) is rewritten to the CURRENT
      preset text and the new column name(s) are appended to a non-empty
      ``result_columns`` / ``line_result_columns``; a query already at the
      current text is skipped silently (its rows are ``seed_company_defaults``'
      or an operator's - a deliberately deleted row is never reseeded);
      anything else (a hand-written query such as prod ``AED_SORENTO``) is
      left byte-untouched;
    * each mapping row is created only when none exists in ANY state -
      ENABLED when the query was just rewritten or its column list already
      carries the column, DISABLED with one WARNING naming the config id
      otherwise.

    Returns rows created + queries replaced; 0 on a schema predating these
    tables. ``tenant_id`` scopes the pass to one tenant (``update_tenant``);
    ``None`` (module Alembic 0032) covers every tenant. Frozen ``sa.table``
    only; the company is resolved WITH the config's own ``tenant_id``.
    """
    needed = {
        "ac_entity_config": _SO_REMARK_ENTITY_CONFIG_COLUMNS,
        "ac_company": _SALES_ORDER_REF_COMPANY_COLUMNS,
        "ac_field_mapping": _SALES_ORDER_REF_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        sa.column("line_result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    # (scope, query key, columns attribute, frozen old text, current text,
    #  columns the new text adds, ((source_path, canonical_field), ...))
    sides = (
        (
            SCOPE_HEADER, "query", "result_columns", _TRANSFERABLE_SO_HEADER_QUERY,
            _REMARK_SO_HEADER_QUERY, ("ShipInfo",), (("ShipInfo", "ship_info"),),
        ),
        (
            SCOPE_LINE, "lineQuery", "line_result_columns", _PRE_REMARK_SO_LINE_QUERY,
            _REMARK_SO_LINE_QUERY, ("FurtherDescription", "SectionHeading"),
            (("FurtherDescription", "line_remark"), ("SectionHeading", "section_heading")),
        ),
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    stmt = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.source_config, entity_config.c.result_columns,
        entity_config.c.line_result_columns,
    ).where(entity_config.c.entity_type == ENTITY_SALES_ORDER)
    if tenant_id is not None:
        stmt = stmt.where(entity_config.c.tenant_id == tenant_id)
    configs = connectable.execute(stmt).fetchall()

    touched = 0
    for config_id, cfg_tenant, company_id, source_config, result_columns, line_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == cfg_tenant,
            )
        ).first()
        if company_row is None or not company_row[0]:
            logger.warning(
                "Sales-order task %s's company could not be resolved under "
                "its own tenant - the SO remark backfill skipped it.",
                config_id,
            )
            continue
        database_name = company_row[0]
        fresh = dict(source_config or {})
        columns_by_attr = {
            "result_columns": list(result_columns or []),
            "line_result_columns": list(line_columns or []),
        }
        state: Dict[str, str] = {}  # scope -> "replaced" | "current" | "other"
        values: Dict[str, Any] = {}
        for scope, query_key, columns_attr, old_tpl, new_tpl, added, _rows in sides:
            stored = fresh.get(query_key)
            old_text = old_tpl.replace("{database}", database_name)
            new_text = new_tpl.replace("{database}", database_name)
            if stored == new_text:
                state[scope] = "current"
                continue
            if stored != old_text:
                state[scope] = "other"
                continue
            fresh[query_key] = new_text
            values["source_config"] = fresh
            columns = columns_by_attr[columns_attr]
            # An EMPTY column list means "never previewed" - leave it empty.
            if columns:
                for name in added:
                    if name not in columns:
                        columns.append(name)
                values[columns_attr] = columns
            state[scope] = "replaced"
            touched += 1
        if values:
            connectable.execute(
                sa.update(entity_config).where(entity_config.c.id == config_id).values(**values)
            )

        for scope, _qk, columns_attr, _old, _new, _added, rows in sides:
            if state[scope] == "current":
                # Already on the current text: nothing to seed, and a row an
                # operator deleted on purpose is never brought back.
                continue
            for source_path, canonical_field in rows:
                has_row = connectable.execute(
                    sa.select(field_mapping.c.id).where(
                        field_mapping.c.tenant_id == cfg_tenant,
                        field_mapping.c.company_id == company_id,
                        field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                        field_mapping.c.scope == scope,
                        field_mapping.c.canonical_field == canonical_field,
                    )
                ).first() is not None
                if has_row:
                    continue
                sort_order = connectable.execute(
                    sa.select(sa.func.coalesce(sa.func.max(field_mapping.c.sort_order), -1) + 1)
                    .where(
                        field_mapping.c.tenant_id == cfg_tenant,
                        field_mapping.c.company_id == company_id,
                        field_mapping.c.entity_type == ENTITY_SALES_ORDER,
                        field_mapping.c.scope == scope,
                    )
                ).scalar()
                enabled = state[scope] == "replaced" or source_path in columns_by_attr[columns_attr]
                connectable.execute(
                    sa.insert(field_mapping).values(
                        id=str(uuid.uuid4()),
                        tenant_id=cfg_tenant,
                        company_id=company_id,
                        entity_type=ENTITY_SALES_ORDER,
                        scope=scope,
                        source_path=source_path,
                        canonical_field=canonical_field,
                        transform="string",
                        formula=None,
                        is_required=False,
                        is_enabled=enabled,
                        is_source_owned=True,
                        sort_order=sort_order,
                    )
                )
                touched += 1
                if not enabled:
                    logger.warning(
                        "Sales-order task %s has a %s query the SO remark backfill "
                        "does not recognise as the AutoCount SO preset - left "
                        "untouched. Add `%s` to the query and enable the "
                        "`%s -> %s` row on the Mapping tab.",
                        config_id, scope, source_path, source_path, canonical_field,
                    )
    return touched


# ── feat/line-fingerprint-sweep ─────────────────────────────────────────────

_FINGERPRINT_BACKFILL_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_config",
}
_FINGERPRINT_BACKFILL_COMPANY_COLUMNS = {"id", "tenant_id", "database_name"}


def backfill_document_fingerprint_queries(
    bind: Any,
    *,
    schema: Optional[str] = AUTOCOUNT_SCHEMA,
    config_ids: Optional[Sequence[str]] = None,
    on_refill: Optional[Callable[[str, str, str, str], None]] = None,
    warn_custom: bool = True,
) -> int:
    """Sets ``source_config["fingerprintQuery"]`` from the entity's own
    preset (with ``{database}`` substituted from the task's OWN company)
    on every DOCUMENT ``ac_entity_config`` row that has none yet. Returns
    the number of rows changed - 0 on a schema that predates the columns
    this touches (module Alembic 0017 and ``update_tenant`` both call it).

    Never overwrites an existing value, customised or not - a task that
    already carries SOME ``fingerprintQuery`` (hand-edited, or already
    backfilled by an earlier run) is left exactly as-is and named in a
    WARNING so an operator who wants the shipped preset can pick it again
    from the query picker. Master tasks (anything not in
    ``DOCUMENT_PRESETS``) are never touched - the sweep does not apply to
    them and the validator itself drops the key for a master.

        !!  FROZEN ``sa.table`` ONLY - NEVER THE LIVE ORM MODEL.  !!
    Same rule, same incident, as ``backfill_shipping_order_container_number``
    above: this runs from module Alembic 0017, so a later migration adding
    a column to either table must never break a fresh ``0001`` -> head
    replay. Only the columns this function actually touches are named.

    Never a bare id lookup: a config's company is resolved WITH the
    config's OWN ``tenant_id`` (the polymorphic-target_id rule) before its
    ``database_name`` is trusted for the substitution.

    SS-RECONCILE-SKIP-FIX (owner OK 27 Oct): also the service's own refill
    (``refill_empty_fingerprint_queries``, on every deploy and before a
    scheduled sweep). A blank/whitespace-only value counts as empty.
    ``config_ids`` narrows the pass to those tasks, ``on_refill(config_id,
    tenant_id, company_id, entity_type)`` is told about each refilled task,
    and ``warn_custom=False`` drops the per-task "left untouched" warning a
    pass that runs on every deploy would otherwise repeat forever.
    """
    needed = {
        "ac_entity_config": _FINGERPRINT_BACKFILL_ENTITY_CONFIG_COLUMNS,
        "ac_company": _FINGERPRINT_BACKFILL_COMPANY_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    from .presets import DOCUMENT_PRESETS

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    # Plan 36 review - optional: a schema without the sweep table has no rows
    # to reset.
    fingerprint_columns = existing_columns(bind, "ac_doc_fingerprint", schema=schema)
    fingerprint_table = (
        sa.table(
            "ac_doc_fingerprint",
            sa.column("tenant_id", sa.String),
            sa.column("company_id", sa.String),
            sa.column("entity_type", sa.String),
            schema=schema,
        )
        if fingerprint_columns and {"tenant_id", "company_id", "entity_type"} <= fingerprint_columns
        else None
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    select = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.entity_type, entity_config.c.source_config,
    ).where(entity_config.c.entity_type.in_(list(DOCUMENT_PRESETS.keys())))
    if config_ids is not None:
        if not config_ids:
            return 0
        select = select.where(entity_config.c.id.in_(list(config_ids)))
    # Row-locked (FOR UPDATE on Postgres, a no-op on SQLite) so a UI Save that
    # commits a custom query between this read and the UPDATE below cannot be
    # overwritten (lost update) - the Save waits, then wins.
    configs = connectable.execute(select.with_for_update()).fetchall()

    touched = 0
    for config_id, tenant_id, company_id, entity_type, source_config in configs:
        preset = DOCUMENT_PRESETS.get(entity_type)
        if not preset or not preset.fingerprint_query:
            continue

        source_config = source_config or {}
        existing = source_config.get("fingerprintQuery")
        if isinstance(existing, str):
            existing = existing.strip()
        if existing:
            if not warn_custom:
                continue
            logger.warning(
                "Task %s already has a fingerprintQuery - the "
                "line-fingerprint-sweep backfill left it untouched.",
                config_id,
            )
            continue

        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]

        fresh = dict(source_config)
        fresh["fingerprintQuery"] = preset.fingerprint_query.replace(
            "{database}", database_name
        )
        connectable.execute(
            sa.update(entity_config)
            .where(entity_config.c.id == config_id)
            .values(source_config=fresh)
        )
        # Plan 36 review: a task whose sweep a pre-36 Save wiped may still
        # hold fingerprint rows from its OLD text; the new text would
        # mismatch them all at once (the plan-06 S1 rule), so drop them.
        if fingerprint_table is not None:
            connectable.execute(
                sa.delete(fingerprint_table).where(
                    fingerprint_table.c.tenant_id == tenant_id,
                    fingerprint_table.c.company_id == company_id,
                    fingerprint_table.c.entity_type == entity_type,
                )
            )
        touched += 1
        if on_refill is not None:
            on_refill(config_id, tenant_id, company_id, entity_type)
    return touched


def refill_empty_fingerprint_queries(
    db: Any, *, config_ids: Optional[Sequence[str]] = None
) -> int:
    """SS-RECONCILE-SKIP-FIX (owner OK 27 Oct) - the service's OWN refill of
    an EMPTY line-check (``fingerprintQuery``) from the entity's preset. An
    empty one silently turns the line check off (line-only changes such as a
    DO transfer then wait for the daily reconcile). Runs on every deploy
    (``bootstrap.install``) and in the scheduler before a task's sweep.

    Idempotent; a non-empty (custom) query is never touched; each refill is
    logged and recorded as an Activity row naming the task. The task's stored
    fingerprints are reset (``backfill_document_fingerprint_queries``), so the
    first sweep after a refill only seeds the baseline. Commits the refill.
    """
    from .activity import ACTIVITY_SUCCESS, record_activity

    refilled: List[Tuple[str, str, str, str]] = []
    touched = backfill_document_fingerprint_queries(
        db,
        schema=default_schema(db.get_bind()),
        config_ids=config_ids,
        on_refill=lambda *row: refilled.append(row),
        warn_custom=False,
    )
    if refilled:
        # Commit the refill BEFORE the Activity writes: a failed Activity
        # insert rolls its session back and must not undo a logged refill.
        db.commit()
    for config_id, tenant_id, company_id, entity_type in refilled:
        logger.warning(
            "autocount task %s (%s, company %s) had an empty line-check query; "
            "refilled it from the %s preset. The next sweep seeds the baseline.",
            config_id, entity_type, company_id, entity_type,
        )
        # Activity writes commit the session, which also commits the refill.
        record_activity(
            db,
            tenant_id=tenant_id,
            operation=f"refill line check query {entity_type}",
            status=ACTIVITY_SUCCESS,
            # The task id, so Developers > Logs finds it by reference.
            external_ref=config_id,
            request={"taskId": config_id, "companyId": company_id, "entityType": entity_type},
            response={"refilledFrom": "preset", "fingerprintsReset": True},
        )
    return touched


# ── sprint-5/06 (AC-06-16..19) - document line linkage backfill ────────────

_LINE_LINKAGE_ENTITY_TYPES = (ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER)

# AC-06-14: the six enabled, not-required line rows PO_PRESET/SPO_PRESET
# gain, as (source_path, canonical_field, transform) - kept here as a plain
# tuple (not read off `presets.PO_PRESET.line`) so this backfill's target
# set is pinned independently of any future preset edit, the same way the
# OLD query text below is pinned independently of any future preset edit.
_LINE_LINKAGE_FIELDS = (
    ("FromSODocKey", "from_so_doc_key", "int"),
    ("FromSODtlKey", "from_so_line_key", "int"),
    ("FromSODocList", "from_so_numbers", "string_list"),
    ("FromPODocKey", "from_po_doc_key", "int"),
    ("FromPODtlKey", "from_po_line_key", "int"),
    ("FromPODocNo", "from_po_number", "string"),
)

# AC-06-13's four header aggregate names, appended verbatim (order pinned)
# to `result_columns` when the header `query` is rewritten below - they only
# enter the SELECT list via the NEW `_PO_HEADER_QUERY`, and the compared-
# column set a paged run's change-detection hashes derives from
# `result_columns` (minus the key columns, `sql_source/source.py`), so
# without this a document whose only change is a newly populated link would
# never re-stage.
_LINE_LINKAGE_AGGREGATE_COLUMNS = (
    "LinkedSOCount", "FromSOKeySum", "LinkedPOCount", "FromPOKeySum",
)

# B1 (review round, BLOCKER) - the seven names `_PO_LINE_QUERY` newly SELECTs
# (AC-06-12), appended to `line_result_columns` in the SAME update that
# rewrites `lineQuery` - the header-side equivalent of
# `_LINE_LINKAGE_AGGREGATE_COLUMNS` above. Six of the seven are a
# `_LINE_LINKAGE_FIELDS` row's own `source_path`; `FromSODocNo` is
# select-only (never mapped to a target) but must still be a recognised
# preview column, or `_replace_line_mapping`'s known-vars gate 422s any
# FORMULA row that names it. Without this, the six ENABLED rows this
# function inserts below reference a `source_path` that is not among the
# task's last-previewed columns - `_replace_line_mapping`
# (`services/company_service.py:1505-1509`) 422s any later Mapping-tab save
# on every one of these existing tasks.
_LINE_LINKAGE_LINE_RESULT_COLUMNS = (
    "FromSODtlKey", "FromSODocKey", "FromSODocNo", "FromSODocList",
    "FromPODtlKey", "FromPODocKey", "FromPODocNo",
)

# The generic PO/SPO header/line/fingerprint queries EXACTLY as they shipped
# on this branch BEFORE slice S1 (frozen on purpose - `git show
# 21e2df32:service_backend/modules/autocount/presets.py`). The byte-identity
# check below is against THIS text, with `{database}` substituted the same
# way `list_mapping_presets`'s "Use preset" picker hands it out - never a
# regenerated string that could silently drift from what a live task
# actually stored before this slice shipped.
_OLD_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, h.Ref AS Ref, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)
_OLD_PO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS ExpectedDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.PODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)
_OLD_PO_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d JOIN {database}.dbo.PO AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
)

_LINE_LINKAGE_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_config", "result_columns",
    "line_result_columns",
}
_LINE_LINKAGE_COMPANY_COLUMNS = {"id", "tenant_id", "database_name"}
_LINE_LINKAGE_FIELD_MAPPING_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "scope", "source_path",
    "canonical_field", "transform", "formula", "is_required", "is_enabled",
    "is_source_owned", "sort_order",
}
# S1 (review round, should-fix) - scoped columns for the `ac_doc_fingerprint`
# sweep this backfill resets below when `fingerprintQuery` is rewritten.
_LINE_LINKAGE_FINGERPRINT_COLUMNS = {"tenant_id", "company_id", "entity_type", "source_ref"}

_LINE_LINKAGE_TARGET_FIELDS = tuple(target for _src, target, _tf in _LINE_LINKAGE_FIELDS)


def backfill_document_line_linkage(bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA) -> int:
    """(AC-06-16/17) for every existing ``purchase_order``/``shipping_order``
    ``ac_entity_config`` row across every tenant/company that already has AT
    LEAST ONE line-scope mapping row (a task with ZERO is skipped entirely -
    see the ``!! S2 !!`` note below):

    * adds the six enabled-or-disabled, not-required line-linkage mapping
      rows of AC-06-14 for any target not already present (an operator's
      own row for that target, in ANY state, is left alone - checked by
      ``canonical_field``, the unique-constraint column, never
      ``source_path``);
    * independently, when the task's stored ``query``/``lineQuery``/
      ``fingerprintQuery`` is byte-identical to the OLD preset text (with
      the task's OWN company ``database_name`` substituted), replaces it
      with the current preset text; when ``query`` itself is replaced this
      way, the four header aggregate names of AC-06-13 are appended to
      ``result_columns`` (they only enter the SELECT list via the NEW
      header query, and the paged run's change-detection hash derives its
      compared-column set from ``result_columns``); when ``lineQuery`` is
      replaced this way, the seven names it newly SELECTs are appended to
      ``line_result_columns`` in the SAME update, and the six rows above
      land ENABLED - see the ``!! B1 !!`` note below; when ``fingerprintQuery``
      is replaced this way, the task's stored ``ac_doc_fingerprint`` rows are
      DELETED (scoped tenant/company/entity) - see the ``!! S1 !!`` note
      below; any statement that is neither the OLD text nor already the NEW
      text is a customisation (including one that happens to match a
      SIBLING company's own substitution) and is left completely untouched,
      with ONE WARNING naming the config id.

    ``sales_order`` never reaches this function's row/query logic at all -
    filtered by ``entity_type`` up front, never by matching query text (a
    ``sales_order`` task given the exact same generic OLD text must still
    be left completely alone, unlogged). Returns the number of individual
    changes made (mapping rows created + statements replaced) - 0 on a
    schema that predates the tables/columns this touches (module Alembic
    0018 and ``update_tenant`` both call this, so it must survive every
    stamp in the chain, not only the one it ships with).

        !!  B1 (review round, BLOCKER) - is_enabled MIRRORS THE lineQuery
            REWRITE.  !!
    An ENABLED row whose ``source_path`` is not among the task's last-
    previewed ``line_result_columns`` 422s any LATER Mapping-tab save
    (``services/company_service.py`` ``_replace_line_mapping``,
    ~1505-1509). The six rows only land enabled when THIS pass rewrote
    ``lineQuery`` to the text that actually selects their source columns
    (proof); left alone (customised, or already migrated by an earlier
    pass) proves nothing either way, so they land disabled - the same
    posture ``presets._seed_rows`` already uses for "a column the task's
    ACTUAL query does not return".

        !!  S2 (review round, should-fix) - ZERO LINE ROWS SKIPS THE TASK
            ENTIRELY.  !!
    A real task reaching this backfill in production already has ordinary
    line mapping (module Alembic 0010 backfilled LINE rows onto every
    existing document task) - zero is the "never even test-queried once"
    state, which belongs to ``EtlService.update_task``'s own first-save
    preset seed (which, as of this slice, carries the six linkage rows
    itself). Seeding a partial six rows here would permanently block that
    seed (its own ``line_empty`` gate would never see zero again).

        !!  S1 (review round, should-fix) - fingerprintQuery REWRITE RESETS
            ITS FINGERPRINT ROWS.  !!
    The rewritten ``fingerprintQuery`` selects extra join columns
    (AC-06-12), so its computed hash changes for EVERY document even when
    that document's own lines never moved. Left in place, the sweep
    (``sync.py`` ~1147-1157) would see every stored fingerprint mismatch its
    freshly computed one at once and stage the task's entire window unpaced.
    Deleting the stored rows (scoped tenant/company/entity) means the sweep
    finds none stored and silently RE-SEEDS instead (``sync.py``
    ~1156-1160's ``seed_only``) - the intentional one-time re-stage of the
    header/line linkage data itself stays owned by ``result_columns``/
    ``line_result_columns`` above, via the PAGED reconcile run's own
    change-detection hash, never this sweep.

        !!  FROZEN ``sa.table`` ONLY - NEVER THE LIVE ORM MODEL.  !!
    Same rule, same incident, as ``backfill_shipping_order_container_number``
    (module Alembic 0006, ``documentation/engineering/storage-and-background-
    jobs.md``): called from module Alembic 0018, so a later migration adding
    a column to any of these three tables must never break a fresh
    ``0001`` -> head replay.

    Never a bare id lookup: a config's company is resolved WITH the
    config's OWN ``tenant_id`` (the polymorphic-target_id rule) before its
    ``database_name`` is trusted for the substitution.
    """
    needed = {
        "ac_entity_config": _LINE_LINKAGE_ENTITY_CONFIG_COLUMNS,
        "ac_company": _LINE_LINKAGE_COMPANY_COLUMNS,
        "ac_field_mapping": _LINE_LINKAGE_FIELD_MAPPING_COLUMNS,
        "ac_doc_fingerprint": _LINE_LINKAGE_FINGERPRINT_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    from .presets import _PO_FINGERPRINT_QUERY, _PO_HEADER_QUERY, _PO_LINE_QUERY

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        sa.column("line_result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )
    doc_fingerprint = sa.table(
        "ac_doc_fingerprint",
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_ref", sa.String),
        schema=schema,
    )

    # Same unwrap `existing_columns` uses, and for the same reason - a
    # `Session.get_bind()` checks out a SECOND pooled connection, blind to
    # the session's own uncommitted work.
    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    configs = connectable.execute(
        sa.select(
            entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
            entity_config.c.entity_type, entity_config.c.source_config,
            entity_config.c.result_columns, entity_config.c.line_result_columns,
        ).where(entity_config.c.entity_type.in_(_LINE_LINKAGE_ENTITY_TYPES))
    ).fetchall()

    touched = 0
    for (
        config_id, tenant_id, company_id, entity_type, source_config,
        result_columns, line_result_columns,
    ) in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]

        #     !!  S2 (review round, should-fix) - ZERO EXISTING LINE ROWS
        #         SKIPS THE TASK ENTIRELY.  !!
        # A real task reaching this backfill in production already has
        # ordinary line mapping (module Alembic 0010 backfilled LINE rows
        # onto every existing document task) - a genuinely EMPTY line scope
        # only happens for a task that was never even test-queried once.
        # THAT state belongs to `EtlService.update_task`'s own first-save
        # preset seed, which (as of this slice's S1) already carries the six
        # linkage rows itself - inserting a partial six rows HERE would set
        # `AcFieldMapping` scope=line rows for the task, so the seed's own
        # `line_empty` gate (`services/etl_service.py`) would never fire
        # again, and the operator would get ONLY the six linkage rows and
        # never the rest of the preset's line fields. `MAX(sort_order)`
        # doubles as this existence check (`NULL` <=> zero rows) and as the
        # next insert's own starting point (S2 nit: `MAX + 1`, never
        # `COUNT` - a prior DELETE leaves a gap `COUNT` would collide into).
        max_sort_order = connectable.execute(
            sa.select(sa.func.max(field_mapping.c.sort_order)).where(
                field_mapping.c.tenant_id == tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == entity_type,
                field_mapping.c.scope == SCOPE_LINE,
            )
        ).scalar()
        if max_sort_order is None:
            continue
        next_sort_order = max_sort_order + 1

        # (b, computed FIRST) the three statements, each an INDEPENDENT
        # check - a customised lineQuery must never block the header query
        # (or fingerprintQuery) from being rewritten, and vice versa
        # (AC-06-17 "per statement"). Computed before (a) below on purpose
        # (B1, review round, BLOCKER): whether `lineQuery` itself was
        # rewritten THIS pass decides whether the six rows (a) are safe to
        # enable AND whether `line_result_columns` gains their source names.
        source_config = source_config or {}
        fresh_config: Dict[str, Any] = dict(source_config)
        config_changed = False
        header_replaced = False
        line_replaced = False
        fingerprint_replaced = False
        customised = False
        for key, old_template, new_template in (
            ("query", _OLD_PO_HEADER_QUERY, _PO_HEADER_QUERY),
            ("lineQuery", _OLD_PO_LINE_QUERY, _PO_LINE_QUERY),
            ("fingerprintQuery", _OLD_PO_FINGERPRINT_QUERY, _PO_FINGERPRINT_QUERY),
        ):
            stored = source_config.get(key)
            old_text = old_template.replace("{database}", database_name)
            new_text = new_template.replace("{database}", database_name)
            if stored == old_text:
                fresh_config[key] = new_text
                config_changed = True
                touched += 1
                if key == "query":
                    header_replaced = True
                elif key == "lineQuery":
                    line_replaced = True
                elif key == "fingerprintQuery":
                    fingerprint_replaced = True
            elif stored != new_text:
                # Neither the OLD preset (customised, or a SIBLING
                # company's own substitution pasted in) nor already the
                # NEW preset (already migrated - silent, never a repeat
                # warning) - left untouched.
                customised = True

        # (a) the six mapping rows. Checked by `canonical_field` (the
        # unique-constraint column) - an operator's own row targeting a
        # linkage field from a different source column still counts as
        # "already there".
        #
        #     !!  B1 (review round, BLOCKER) - is_enabled MIRRORS THE
        #         lineQuery REWRITE, NOT A BLANKET True.  !!
        # `_replace_line_mapping` 422s any ENABLED row whose `source_path`
        # is not among `line_result_columns` (`services/company_service.py`
        # ~1505-1509). `line_replaced` (just computed above) is the ONLY
        # proof this pass has that the task's query actually selects these
        # six rows' source columns - unrewritten (customised, or already the
        # NEW text from an earlier pass) proves nothing either way, so the
        # row lands disabled, same posture `presets._seed_rows` already uses
        # for "a column the task's ACTUAL query does not return".
        existing_targets = {
            row[0]
            for row in connectable.execute(
                sa.select(field_mapping.c.canonical_field).where(
                    field_mapping.c.tenant_id == tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == entity_type,
                    field_mapping.c.scope == SCOPE_LINE,
                    field_mapping.c.canonical_field.in_(_LINE_LINKAGE_TARGET_FIELDS),
                )
            ).fetchall()
        }
        for source_path, target, transform in _LINE_LINKAGE_FIELDS:
            if target in existing_targets:
                continue
            connectable.execute(
                sa.insert(field_mapping).values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    scope=SCOPE_LINE,
                    source_path=source_path,
                    canonical_field=target,
                    transform=transform,
                    formula=None,
                    is_required=False,
                    is_enabled=line_replaced,
                    # Not a NOT-NULL column DEFAULT at the database level
                    # (`AcFieldMapping.is_source_owned`'s `default=True` is
                    # ORM-side only) - a frozen `sa.table` insert must
                    # state it explicitly or a strict backend (SQLite)
                    # rejects the row outright.
                    is_source_owned=True,
                    sort_order=next_sort_order,
                )
            )
            next_sort_order += 1
            touched += 1

        # (c) ONE update carrying whichever of source_config/result_columns/
        # line_result_columns actually changed this pass.
        update_values: Dict[str, Any] = {}
        if config_changed:
            update_values["source_config"] = fresh_config
        if header_replaced:
            columns_list = list(result_columns or [])
            for name in _LINE_LINKAGE_AGGREGATE_COLUMNS:
                if name not in columns_list:
                    columns_list.append(name)
            update_values["result_columns"] = columns_list
            # (codex round, finding 1) - `compared_columns_for`
            # (`sql_source/hashing.py`) hashes ONLY an explicit non-empty
            # `comparedColumns` picklist, so `result_columns` alone gaining
            # these four names is inert for such a task - the picklist
            # filters them straight back out and the document never
            # re-stages. Appended in the SAME update, preserving the
            # operator's own entries and order, no duplicates. An empty/
            # absent picklist already means "every result column minus the
            # keys" (`compared_columns_for`'s other branch) - left alone.
            compared_columns = fresh_config.get("comparedColumns")
            if compared_columns:
                compared_list = list(compared_columns)
                for name in _LINE_LINKAGE_AGGREGATE_COLUMNS:
                    if name not in compared_list:
                        compared_list.append(name)
                fresh_config["comparedColumns"] = compared_list
        if line_replaced:
            # B1 - the SAME update that rewrites `lineQuery` to the text
            # that now selects these seven columns must also declare them,
            # or the six rows just inserted ENABLED above 422 the very next
            # Mapping-tab save.
            line_columns_list = list(line_result_columns or [])
            for name in _LINE_LINKAGE_LINE_RESULT_COLUMNS:
                if name not in line_columns_list:
                    line_columns_list.append(name)
            update_values["line_result_columns"] = line_columns_list
        if update_values:
            connectable.execute(
                sa.update(entity_config)
                .where(entity_config.c.id == config_id)
                .values(**update_values)
            )

        #     !!  S1 (review round, should-fix) - A REWRITTEN
        #         fingerprintQuery RESETS ITS FINGERPRINT ROWS.  !!
        # `fingerprintQuery`'s new text selects extra join columns
        # (AC-06-12), so its computed hash changes for every document even
        # when nothing about that document's own lines changed - left in
        # place, the NEXT sweep would see every stored fingerprint mismatch
        # its freshly computed one at once and stage the task's ENTIRE
        # window unpaced (`sync.py` ~1147-1157: `changed_refs` is exactly
        # "stored fingerprint exists AND differs"). Deleting the stored rows
        # here means the sweep instead finds no stored fingerprint at all
        # for any of them (`stored.get(ref) is None`) and silently RE-SEEDS
        # (`sync.py` ~1156-1160's `seed_only`), never stages. The intentional
        # one-time re-stage of the header/line linkage data itself stays
        # owned by `result_columns`/`line_result_columns` above, via the
        # PAGED reconcile run's own change-detection hash - never this sweep.
        if fingerprint_replaced:
            connectable.execute(
                sa.delete(doc_fingerprint).where(
                    doc_fingerprint.c.tenant_id == tenant_id,
                    doc_fingerprint.c.company_id == company_id,
                    doc_fingerprint.c.entity_type == entity_type,
                )
            )

        if customised:
            logger.warning(
                "%s task %s has a query/lineQuery/fingerprintQuery the "
                "line-linkage backfill does not recognise as the "
                "AutoCount PO/SPO preset - left untouched. Add the "
                "FromSO*/FromPO* columns by hand to pick up line linkage.",
                entity_type, config_id,
            )
    return touched


# ── ITEM-TYPE-SS (partner of sorento #1450) ─────────────────────────────────

_ITEM_TYPE_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_impl",
    "source_config", "result_columns",
}
_ITEM_TYPE_COMPANY_COLUMNS = {"id", "tenant_id"}
_ITEM_TYPE_FIELD_MAPPING_COLUMNS = _SALES_ORDER_REF_FIELD_MAPPING_COLUMNS
# The preset's own path and source column, FROZEN here (never read off the
# live preset) - a later preset edit must not change what this migration did.
_ITEM_TYPE_HTTP_PATH = "/itembypage"
_ITEM_TYPE_SOURCE_COLUMN = "ItemType"


def backfill_product_item_type(
    bind: Any,
    *,
    schema: Optional[str] = AUTOCOUNT_SCHEMA,
    tenant_id: Optional[str] = None,
) -> int:
    """Give every EXISTING ``product`` task an ``ItemType -> item_type_code``
    header row (``string``, not required, source-owned, next ``sort_order``)
    when none exists in ANY state - the preset only seeds a task's FIRST
    clean save, so without this the field never reaches tenants already
    syncing products.

    ENABLED when the source is known to carry the column: an
    ``autocount_http`` task still on the preset's ``/itembypage`` path (every
    row of that endpoint carries ``ItemType``), or any task whose cached
    ``result_columns`` already list ``ItemType``. Otherwise DISABLED with one
    WARNING naming the config id (an operator-authored SQL query or custom
    path the backfill cannot vouch for).

    No query text marks a product HTTP task "already migrated", so an
    operator who deletes the row would see it reseeded on every pass: module
    Alembic 0028 runs it once, and ``update_tenant`` only when upgrading from
    below 0.14.0 - and then for THAT tenant only (``tenant_id``): the
    version gate is per tenant, so an unscoped sweep would let one tenant's
    late update reseed a row another, already-updated tenant deleted.
    ``tenant_id=None`` (the migration) sweeps every tenant.
    Returns the number of rows created; 0 on a schema
    predating these tables. Frozen ``sa.table`` only, company resolved WITH
    the config's own ``tenant_id`` (polymorphic-target_id rule).
    """
    return _backfill_source_owned_header_row(
        bind,
        schema=schema,
        tenant_id=tenant_id,
        entity_type=ENTITY_PRODUCT,
        source_column=_ITEM_TYPE_SOURCE_COLUMN,
        canonical_field="item_type_code",
        known_good=lambda source_impl, source_config: (
            source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
            and source_config.get("path") == _ITEM_TYPE_HTTP_PATH
        ),
        task_label="Product",
        known_good_label="the AutoCount `/itembypage` preset",
    )



# ── ITEM-CLASS (partner of sorento-crm ITEM-CLASS) ──────────────────────────

# FROZEN like the ItemType pair above - a later preset edit must not change
# what module Alembic 0034 did.
_ITEM_CLASS_SOURCE_COLUMN = "ItemClass"


def backfill_product_item_class(
    bind: Any,
    *,
    schema: Optional[str] = AUTOCOUNT_SCHEMA,
    tenant_id: Optional[str] = None,
) -> int:
    """Give every EXISTING ``product`` task an ``ItemClass -> item_class_code``
    header row: ``backfill_product_item_type`` exactly (see its docstring),
    for AutoCount's ``ItemClass``. ENABLED on the ``/itembypage`` preset path
    (every row of that endpoint carries ``ItemClass``, blank on most items) or
    when the cached ``result_columns`` list it, DISABLED with one WARNING
    otherwise. ``skip_unmapped`` (BL-SS-300): a task with NO header rows is
    left to its first-save preset seed, which now carries the row itself. Module Alembic 0034 runs it once; ``update_tenant`` only from
    below 0.20.0 and for that tenant only."""
    return _backfill_source_owned_header_row(
        bind,
        schema=schema,
        tenant_id=tenant_id,
        entity_type=ENTITY_PRODUCT,
        source_column=_ITEM_CLASS_SOURCE_COLUMN,
        canonical_field="item_class_code",
        known_good=lambda source_impl, source_config: (
            source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
            and source_config.get("path") == _ITEM_TYPE_HTTP_PATH
        ),
        task_label="Product",
        known_good_label="the AutoCount `/itembypage` preset",
        # BL-SS-300: an empty product task keeps its first-save preset seed.
        skip_unmapped=True,
    )


def _backfill_source_owned_header_row(
    bind: Any,
    *,
    schema: Optional[str],
    tenant_id: Optional[str],
    entity_type: str,
    source_column: str,
    canonical_field: str,
    known_good: Callable[[Optional[str], Dict[str, Any]], bool],
    task_label: str,
    known_good_label: str,
    skip_unmapped: bool = False,
) -> int:
    """Shared body of the "give every EXISTING ``entity_type`` task one
    ``source_column -> canonical_field`` header row" backfills (ITEM-TYPE-SS,
    SS-DEBTOR-AGENT). A row is created only when none exists for
    ``canonical_field`` in ANY state; ENABLED when ``known_good`` vouches for
    the source or its cached ``result_columns`` list ``source_column``,
    otherwise DISABLED with one WARNING naming the config id.
    ``skip_unmapped`` leaves a task with NO header rows at all untouched: its
    first save / ``update_tenant`` seed fills the whole default or preset
    mapping only while the mapping is completely empty, so a lone backfilled
    row there would block that seed. ``tenant_id``
    scopes the sweep (``None`` = every tenant). Returns rows created; 0 on a
    schema predating these tables."""
    needed = {
        "ac_entity_config": _ITEM_TYPE_ENTITY_CONFIG_COLUMNS,
        "ac_company": _ITEM_TYPE_COMPANY_COLUMNS,
        "ac_field_mapping": _ITEM_TYPE_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_impl", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind

    config_query = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.source_impl, entity_config.c.source_config,
        entity_config.c.result_columns,
    ).where(entity_config.c.entity_type == entity_type)
    if tenant_id is not None:
        config_query = config_query.where(entity_config.c.tenant_id == tenant_id)
    configs = connectable.execute(config_query).fetchall()

    created = 0
    for config_id, config_tenant_id, company_id, source_impl, source_config, result_columns in configs:
        company_ok = connectable.execute(
            sa.select(company_table.c.id).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == config_tenant_id,
            )
        ).first() is not None
        if not company_ok:
            logger.warning(
                "%s task %s's company could not be resolved under its own "
                "tenant - the `%s` backfill skipped it.",
                task_label, config_id, source_column,
            )
            continue

        has_row = connectable.execute(
            sa.select(field_mapping.c.id).where(
                field_mapping.c.tenant_id == config_tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == entity_type,
                field_mapping.c.scope == SCOPE_HEADER,
                field_mapping.c.canonical_field == canonical_field,
            )
        ).first() is not None
        if has_row:
            # An operator's own row (or one an earlier pass seeded) - never
            # duplicated or modified, in ANY state.
            continue

        if skip_unmapped and connectable.execute(
            sa.select(field_mapping.c.id).where(
                field_mapping.c.tenant_id == config_tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == entity_type,
                field_mapping.c.scope == SCOPE_HEADER,
            )
        ).first() is None:
            continue

        source_config = source_config or {}
        enabled = (
            source_column in list(result_columns or [])
            or known_good(source_impl, source_config)
        )
        sort_order = connectable.execute(
            sa.select(sa.func.coalesce(sa.func.max(field_mapping.c.sort_order), -1) + 1)
            .where(
                field_mapping.c.tenant_id == config_tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == entity_type,
                field_mapping.c.scope == SCOPE_HEADER,
            )
        ).scalar()
        connectable.execute(
            sa.insert(field_mapping).values(
                id=str(uuid.uuid4()),
                tenant_id=config_tenant_id,
                company_id=company_id,
                entity_type=entity_type,
                scope=SCOPE_HEADER,
                source_path=source_column,
                canonical_field=canonical_field,
                transform="string",
                formula=None,
                is_required=False,
                is_enabled=enabled,
                is_source_owned=True,
                sort_order=sort_order,
            )
        )
        created += 1
        if not enabled:
            logger.warning(
                "%s task %s's source is not %s and does not list `%s` - the "
                "`%s -> %s` row was added DISABLED. Select `%s` in the source "
                "and enable the row on the Mapping tab.",
                task_label, config_id, known_good_label, source_column,
                source_column, canonical_field, source_column,
            )
    return created


# ── SS-DEBTOR-AGENT (partner of sorento CUSTOMER-SALES-AGENT) ───────────────

# FROZEN here like the ItemType pair above - a later preset edit must not
# change what this migration did.
_SALES_AGENT_HTTP_PATH = "/debtorbypage"
_SALES_AGENT_SOURCE_COLUMN = "SalesAgent"


def backfill_customer_sales_agent(
    bind: Any,
    *,
    schema: Optional[str] = AUTOCOUNT_SCHEMA,
    tenant_id: Optional[str] = None,
) -> int:
    """Give every EXISTING ``customer`` task a ``SalesAgent ->
    sales_agent_code`` header row (``string``, not required, source-owned,
    next ``sort_order``) when none exists in ANY state - the default mapping
    and the HTTP preset only seed a task's FIRST save, so without this the
    agent never reaches tenants already syncing customers.

    ENABLED when the source is known to carry the column: the vendor
    ``autocount_read`` Debtor API (every row carries ``SalesAgent``), an
    ``autocount_http`` task still on the preset's ``/debtorbypage`` path, or
    any task whose cached ``result_columns`` list ``SalesAgent``. Otherwise
    DISABLED with one WARNING naming the config id. A task with NO mapping
    rows is left alone - its default/preset seed (which already carries the
    row) runs only while the mapping is empty, and a lone row would block it.

    Version-gated exactly like ``backfill_product_item_type`` (module Alembic
    0029 once, ``update_tenant`` only from below 0.15.0 and only for THAT
    tenant) so an operator's deliberate delete is never reseeded.
    """
    return _backfill_source_owned_header_row(
        bind,
        schema=schema,
        tenant_id=tenant_id,
        entity_type=ENTITY_CUSTOMER,
        source_column=_SALES_AGENT_SOURCE_COLUMN,
        canonical_field="sales_agent_code",
        known_good=lambda source_impl, source_config: (
            source_impl == SOURCE_IMPL_AUTOCOUNT_READ
            or (
                source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
                and source_config.get("path") == _SALES_AGENT_HTTP_PATH
            )
        ),
        task_label="Customer",
        known_good_label="the AutoCount Debtor API or the `/debtorbypage` preset",
        # `customer` is in BOTH `DEFAULT_MAPPINGS` (the `update_tenant` seed)
        # and `HTTP_PRESETS` (the first-save seed), each gated on a
        # completely EMPTY mapping - and both already carry the row.
        skip_unmapped=True,
    )


# ── AC-CONSIGN-PULL - consignment `TransferedQty` (CRM contract 2.9) ────────
#
# The #122 consignment preset texts, pinned VERBATIM (the frozen-text rule of
# `_OLD_PO_HEADER_QUERY_TEMPLATE` / `_OLD_SO_HEADER_QUERY` above): a task whose
# stored header / line / fingerprint query is byte-identical to its company's
# substitution of these is rewritten to the CURRENT `presets.CONSIGNMENT_PRESET`
# text (which adds `TransferedQty` on the lines and a `TransferedSum`
# aggregate on the header and the fingerprint sweep). A customised query is
# left alone with a WARNING naming the config id.
_OLD_CONSIGNMENT_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, h.DocDate AS DocDate, "
    "c.AutoKey AS DebtorAutoKey, h.DebtorCode AS DebtorCode, h.DebtorName AS DebtorName, "
    "h.SalesAgent AS SalesAgent, h.Ref AS Ref, h.Description AS Description, "
    "h.RefDocNo AS RefDocNo, h.CurrencyCode AS CurrencyCode, h.Note AS Note, "
    "h.Cancelled AS Cancelled, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.SubTotalSum AS SubTotalSum, "
    "l.MaxDtlKey AS MaxDtlKey, l.LinkedLineCount AS LinkedLineCount, "
    "l.FromDocKeySum AS FromDocKeySum "
    "FROM {database}.dbo.Consignment AS h "
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
    "OUTER APPLY (SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey, "
    "COUNT(d.FromDocDtlKey) AS LinkedLineCount, SUM(d.FromDocDtlKey) AS FromDocKeySum "
    "FROM {database}.dbo.ConsignmentDTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL) AS l"
)
_OLD_CONSIGNMENT_LINE_QUERY = (
    "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey, d.Seq AS Seq, "
    "i.AutoKey AS ItemAutoKey, d.ItemCode AS ItemCode, d.Description AS Description, "
    "w.AutoKey AS LocationAutoKey, d.Location AS Location, d.Qty AS Qty, "
    "d.UOM AS UOM, d.UnitPrice AS UnitPrice, d.SubTotal AS SubTotal, "
    "d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, "
    "d.FromDocDtlKey AS FromDocDtlKey "
    "FROM {database}.dbo.ConsignmentDTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)
_OLD_CONSIGNMENT_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "MAX(d.DtlKey) AS MaxDtlKey, SUM(d.FromDocDtlKey) AS FromDocKeySum, "
    "COUNT(d.FromDocDtlKey) AS LinkedLineCount "
    "FROM {database}.dbo.ConsignmentDTL AS d "
    "JOIN {database}.dbo.Consignment AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
)

_CONSIGNMENT_BACKFILL_ENTITY_CONFIG_COLUMNS = {
    "id", "tenant_id", "company_id", "entity_type", "source_config",
    "result_columns", "line_result_columns",
}
_CONSIGNMENT_BACKFILL_COMPANY_COLUMNS = {"id", "tenant_id", "database_name"}
_CONSIGNMENT_BACKFILL_FIELD_MAPPING_COLUMNS = _SHIPPING_ORDER_BACKFILL_FIELD_MAPPING_COLUMNS

_CONSIGNMENT_QUERY_KEYS = (
    ("query", "header_query", _OLD_CONSIGNMENT_HEADER_QUERY),
    ("lineQuery", "line_query", _OLD_CONSIGNMENT_LINE_QUERY),
    ("fingerprintQuery", "fingerprint_query", _OLD_CONSIGNMENT_FINGERPRINT_QUERY),
)


def backfill_consignment_transferred_qty(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA, tenant_id: Optional[str] = None,
) -> int:
    """AC-31-04 - bring every existing ``consignment`` task onto the
    ``TransferedQty`` preset. Returns the number of changes made (tasks
    rewritten + mapping rows created); 0 on a schema that predates the
    columns this touches (module Alembic 0030 and ``update_tenant`` both call
    it).

    Per task, each step independent and idempotent:

    (a) **Queries.** When the stored header ``query`` is byte-identical to the
        company's substitution of the #122 text, every stored query that is
        still a #122 text (header / ``lineQuery`` / ``fingerprintQuery``) is
        replaced with the current preset's; ``TransferedSum`` is appended to
        ``result_columns`` (so it enters the row hash - every consignment
        re-stages ONCE, intended: it is how ``TransferedQty`` reaches a 2.9
        CRM); ``TransferedQty`` joins ``line_result_columns`` ONLY when the
        stored ``lineQuery`` is now the preset text (a customised line query
        does not select it, so it is never advertised). A header query
        already at the new text is skipped silently; anything else is
        customised: left untouched, one WARNING naming the config id.
    (b) **Mapping row.** ``TransferedQty -> qty_transferred`` (line scope,
        ``decimal``, optional) unless a row for ``qty_transferred`` exists in
        ANY state - ENABLED when the task's line columns include
        ``TransferedQty`` (after (a)), DISABLED otherwise (a customised query
        that does not select it would map nothing).

    ``tenant_id`` (``update_tenant``) scopes the pass to one tenant; ``None``
    (the deploy migration) covers every tenant.

    Frozen ``sa.table`` only, never the live ORM model; a company is
    resolved WITH the config's own ``tenant_id`` (polymorphic-target_id rule).
    Does not commit - the caller (Alembic / ``update_tenant``) owns that.
    """
    needed = {
        "ac_entity_config": _CONSIGNMENT_BACKFILL_ENTITY_CONFIG_COLUMNS,
        "ac_company": _CONSIGNMENT_BACKFILL_COMPANY_COLUMNS,
        "ac_field_mapping": _CONSIGNMENT_BACKFILL_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    from .canonical.documents import ENTITY_CONSIGNMENT
    from .presets import CONSIGNMENT_PRESET

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        sa.column("line_result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind
    select_configs = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.source_config, entity_config.c.result_columns,
        entity_config.c.line_result_columns,
    ).where(entity_config.c.entity_type == ENTITY_CONSIGNMENT)
    if tenant_id is not None:
        select_configs = select_configs.where(entity_config.c.tenant_id == tenant_id)
    configs = connectable.execute(select_configs).fetchall()

    touched = 0
    for config_id, config_tenant_id, company_id, source_config, result_columns, line_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == config_tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]

        # (a) the queries.
        source_config = dict(source_config or {})
        line_columns_list = [str(c) for c in (line_columns or [])]
        stored_header = source_config.get("query")
        old_header = _OLD_CONSIGNMENT_HEADER_QUERY.replace("{database}", database_name)
        new_header = CONSIGNMENT_PRESET.header_query.replace("{database}", database_name)
        if stored_header == old_header:
            for key, preset_attr, old_template in _CONSIGNMENT_QUERY_KEYS:
                old_text = old_template.replace("{database}", database_name)
                if source_config.get(key) == old_text:
                    source_config[key] = getattr(CONSIGNMENT_PRESET, preset_attr).replace(
                        "{database}", database_name
                    )
            columns_list = [str(c) for c in (result_columns or [])]
            if "TransferedSum" not in columns_list:
                # The header query was just rewritten, so it now selects it.
                columns_list.append("TransferedSum")
            # Review (security + reviewer): a CUSTOMISED `lineQuery` beside a
            # preset header is NOT rewritten above, so it does not select
            # TransferedQty - never advertise it in `line_result_columns`
            # (the mapping picker's source list) nor enable its row. Keyed on
            # what the stored line query now actually is (PO backfill B1).
            new_line = CONSIGNMENT_PRESET.line_query.replace("{database}", database_name)
            if source_config.get("lineQuery") == new_line and "TransferedQty" not in line_columns_list:
                line_columns_list.append("TransferedQty")
            connectable.execute(
                sa.update(entity_config)
                .where(entity_config.c.id == config_id)
                .values(
                    source_config=source_config,
                    result_columns=columns_list,
                    line_result_columns=line_columns_list,
                )
            )
            touched += 1
        elif stored_header != new_header:
            logger.warning(
                "Consignment task %s has a header query the TransferedQty "
                "backfill does not recognise as the AutoCount Consignment "
                "preset - left untouched. Add `d.TransferedQty AS "
                "TransferedQty` to its line query (and a TransferedSum "
                "aggregate to its header) to send TransferedQty to a 2.9 CRM.",
                config_id,
            )

        # (b) the mapping row, in any state = already there.
        has_row = connectable.execute(
            sa.select(field_mapping.c.id).where(
                field_mapping.c.tenant_id == config_tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == ENTITY_CONSIGNMENT,
                field_mapping.c.scope == SCOPE_LINE,
                field_mapping.c.canonical_field == "qty_transferred",
            )
        ).first() is not None
        if not has_row:
            sort_order = connectable.execute(
                sa.select(sa.func.count())
                .select_from(field_mapping)
                .where(
                    field_mapping.c.tenant_id == config_tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == ENTITY_CONSIGNMENT,
                    field_mapping.c.scope == SCOPE_LINE,
                )
            ).scalar() or 0
            connectable.execute(
                sa.insert(field_mapping).values(
                    id=str(uuid.uuid4()),
                    tenant_id=config_tenant_id,
                    company_id=company_id,
                    entity_type=ENTITY_CONSIGNMENT,
                    scope=SCOPE_LINE,
                    source_path="TransferedQty",
                    canonical_field="qty_transferred",
                    transform="decimal",
                    formula=None,
                    is_required=False,
                    is_enabled="TransferedQty" in line_columns_list,
                    is_source_owned=True,
                    sort_order=sort_order,
                )
            )
            touched += 1
    return touched


# ── Lane SS-BILLING-DO-API - IV/CS line query off DODTL (module 0032) ────────
#
# The plan-32 (#127) IV/CS line query, verbatim (`{database}` unsubstituted).
# FROZEN: a later preset edit must never change what this pass recognises.
_OLD_BILLING_DO_LINE_TEMPLATE = (
    "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey, d.Seq AS Seq, "
    "i.AutoKey AS ItemAutoKey, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.UOM AS UOM, d.Qty AS Qty, "
    "d.UnitPrice AS UnitPrice, d.DiscountAmt AS DiscountAmt, "
    "d.SubTotalExTax AS SubTotalExTax, d.TaxCode AS TaxCode, "
    "d.TaxRate AS TaxRate, d.Tax AS Tax, d.SubTotal AS SubTotal, "
    "d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, "
    "d.FromDocDtlKey AS FromDocDtlKey, so.DocKey AS LinkSODocKey, "
    "dd.DocKey AS LinkDODocKey "
    "FROM {database}.dbo.<LINE> AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.SODTL AS so ON d.FromDocType = 'SO' AND so.DtlKey = d.FromDocDtlKey "
    "LEFT JOIN {database}.dbo.DODTL AS dd ON d.FromDocType = 'DO' AND dd.DtlKey = d.FromDocDtlKey "
    "WHERE d.DocKey = :doc_key AND (d.SubTotal <> 0 OR d.Qty IS NOT NULL)"
)
_OLD_BILLING_DO_LINE_QUERIES: Dict[str, str] = {
    "invoice": _OLD_BILLING_DO_LINE_TEMPLATE.replace("<LINE>", "IVDTL"),
    "cash_sale": _OLD_BILLING_DO_LINE_TEMPLATE.replace("<LINE>", "CSDTL"),
}
# What 0032 rewrites TO - frozen too, so a later preset edit never changes
# what this migration writes (pinned equal to today's preset by a test).
_NEW_BILLING_DO_LINE_QUERIES: Dict[str, str] = {
    entity_type: old.replace(", dd.DocKey AS LinkDODocKey", "", 1).replace(
        " LEFT JOIN {database}.dbo.DODTL AS dd ON d.FromDocType = 'DO' "
        "AND dd.DtlKey = d.FromDocDtlKey", "", 1,
    )
    for entity_type, old in _OLD_BILLING_DO_LINE_QUERIES.items()
}
_BILLING_DO_LINK_COLUMN = "LinkDODocKey"


def backfill_billing_do_link_queries(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA, tenant_id: Optional[str] = None,
) -> int:
    """Lane SS-BILLING-DO-API (owner ruling 25 Oct: the AutoCount admin will
    not grant ``DODTL``) - move every existing ``invoice`` / ``cash_sale``
    task off the plan-32 line query that joins it. Returns the number of
    changes made (tasks rewritten + mapping rows disabled); 0 on a schema
    that predates the columns this touches.

    Per task: when the stored ``lineQuery`` is byte-identical to the
    company's substitution of the plan-32 text, it becomes the frozen
    DODTL-free preset text (``_NEW_BILLING_DO_LINE_QUERIES``), ``LinkDODocKey`` leaves ``line_result_columns``
    (the query no longer selects it) and every ENABLED line row reading
    ``LinkDODocKey`` is DISABLED (an enabled row on an unselected column
    422s the next Mapping-tab save; the engine ignores ``link_do_doc_key``
    anyway - the DO DocKey now comes from the DO feed ledger). A query
    already at the new text is skipped silently; anything else is customised:
    left untouched, one WARNING naming the config id (it still reads DODTL
    and fails loudly at Preview without the grant - never an unlinked push).

    No row hash moves (``result_columns`` is untouched), so nothing
    re-stages because of this pass. ``tenant_id`` (``update_tenant``) scopes
    the pass; ``None`` (the deploy migration) covers every tenant. Frozen
    ``sa.table`` only, company resolved WITH the config's own ``tenant_id``.
    Does not commit - the caller owns that.
    """
    needed = {
        "ac_entity_config": _CONSIGNMENT_BACKFILL_ENTITY_CONFIG_COLUMNS,
        "ac_company": _CONSIGNMENT_BACKFILL_COMPANY_COLUMNS,
        "ac_field_mapping": {
            "id", "tenant_id", "company_id", "entity_type", "scope", "source_path",
            "is_enabled",
        },
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    new_templates = _NEW_BILLING_DO_LINE_QUERIES
    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("line_result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("is_enabled", sa.Boolean),
        schema=schema,
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind
    select_configs = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.entity_type, entity_config.c.source_config,
        entity_config.c.line_result_columns,
    ).where(entity_config.c.entity_type.in_(list(_OLD_BILLING_DO_LINE_QUERIES)))
    if tenant_id is not None:
        select_configs = select_configs.where(entity_config.c.tenant_id == tenant_id)
    configs = connectable.execute(select_configs).fetchall()

    touched = 0
    for config_id, config_tenant_id, company_id, entity_type, source_config, line_columns in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == config_tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]
        source_config = dict(source_config or {})
        stored = source_config.get("lineQuery")
        old = _OLD_BILLING_DO_LINE_QUERIES[entity_type].replace("{database}", database_name)
        new = new_templates[entity_type].replace("{database}", database_name)
        if stored != old:
            if stored != new:
                logger.warning(
                    "Billing task %s (%s) has a line query the DO-link backfill does not "
                    "recognise as the AutoCount preset - left untouched. Remove its DODTL "
                    "join: DO-sourced lines now link through the Delivery Orders feed "
                    "ledger, and the DODTL grant is not available.",
                    config_id, entity_type,
                )
            continue
        source_config["lineQuery"] = new
        connectable.execute(
            sa.update(entity_config)
            .where(entity_config.c.id == config_id)
            .values(
                source_config=source_config,
                # NULL = never previewed (the mapping save skips its column
                # check) - must stay NULL, never become "zero columns".
                line_result_columns=None if line_columns is None else [
                    str(c) for c in line_columns if str(c) != _BILLING_DO_LINK_COLUMN
                ],
            )
        )
        touched += 1
        disabled = connectable.execute(
            sa.update(field_mapping)
            .where(
                field_mapping.c.tenant_id == config_tenant_id,
                field_mapping.c.company_id == company_id,
                field_mapping.c.entity_type == entity_type,
                field_mapping.c.scope == SCOPE_LINE,
                field_mapping.c.source_path == _BILLING_DO_LINK_COLUMN,
                field_mapping.c.is_enabled.is_(True),
            )
            .values(is_enabled=False)
        )
        touched += disabled.rowcount or 0
    return touched


# ── Plan 35 (SS-BILLING-PRESET-FIX) - billing presets vs the real schema (module 0033) ──
#
# The scout AC-BILLING-ACCESS-CHECK (27 Oct) ran the plan-32 billing queries on
# the read-only grant: `CS` has no `DocStatus`, `DNDTL` has no `FromDoc*`,
# ARDN / ARCN carry `Cancelled`, a draft is `D`, and `DODTL` IS granted. The
# texts below are what each task was stored with before plan 35, verbatim
# (`{database}` unsubstituted). FROZEN: a later preset edit must never change
# what this pass recognises or writes (the targets are pinned equal to
# today's preset by a test). IV/CS lines are what 0032 wrote; they go back to
# what 0032 read (the PR #127 DODTL join).
_PRE35_CS_HEADER = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, h.DocDate AS DocDate, h.DocStatus AS "
    "DocStatus, c.AutoKey AS DebtorAutoKey, h.DebtorCode AS DebtorCode, h.DebtorName AS "
    "DebtorName, h.SalesAgent AS SalesAgent, h.CurrencyCode AS CurrencyCode, "
    "h.CurrencyRate AS CurrencyRate, h.TotalExTax AS TotalExTax, h.Tax AS Tax, h.NetTotal "
    "AS NetTotal, h.LocalNetTotal - h.LocalTax AS LocalNetExTax, h.Ref AS Ref, "
    "h.Description AS Description, h.Cancelled AS Cancelled, h.LastModified AS "
    "LastModified, l.LineFpCount AS LineFpCount, l.LineFpQty AS LineFpQty, "
    "l.LineFpSubTotal AS LineFpSubTotal, l.LineFpTax AS LineFpTax, l.LineFpMaxDtlKey AS "
    "LineFpMaxDtlKey, l.LineFpLinked AS LineFpLinked, l.LineFpTransfered AS "
    "LineFpTransfered FROM {database}.dbo.CS AS h LEFT JOIN {database}.dbo.Debtor AS c ON "
    "c.AccNo = h.DebtorCode OUTER APPLY (SELECT COUNT(*) AS LineFpCount, SUM(d.Qty) AS "
    "LineFpQty, SUM(d.SubTotal) AS LineFpSubTotal, SUM(d.Tax) AS LineFpTax, MAX(d.DtlKey) "
    "AS LineFpMaxDtlKey, COUNT(d.FromDocDtlKey) AS LineFpLinked, SUM(d.TransferedQty) AS "
    "LineFpTransfered FROM {database}.dbo.CSDTL AS d WHERE d.DocKey = h.DocKey AND "
    "(d.SubTotal <> 0 OR d.Qty IS NOT NULL)) AS l"
)
_PRE35_DN_HEADER = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, h.DocDate AS DocDate, h.DocStatus AS "
    "DocStatus, c.AutoKey AS DebtorAutoKey, h.DebtorCode AS DebtorCode, h.DebtorName AS "
    "DebtorName, h.SalesAgent AS SalesAgent, h.CurrencyCode AS CurrencyCode, "
    "h.CurrencyRate AS CurrencyRate, h.TotalExTax AS TotalExTax, h.Tax AS Tax, h.NetTotal "
    "AS NetTotal, h.LocalNetTotal - h.LocalTax AS LocalNetExTax, h.Ref AS Ref, "
    "h.Description AS Description, h.OurInvoiceNo AS OurInvoiceNo, h.Cancelled AS "
    "Cancelled, h.LastModified AS LastModified, l.LineFpCount AS LineFpCount, l.LineFpQty "
    "AS LineFpQty, l.LineFpSubTotal AS LineFpSubTotal, l.LineFpTax AS LineFpTax, "
    "l.LineFpMaxDtlKey AS LineFpMaxDtlKey, l.LineFpLinked AS LineFpLinked FROM "
    "{database}.dbo.DN AS h LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
    "OUTER APPLY (SELECT COUNT(*) AS LineFpCount, SUM(d.Qty) AS LineFpQty, SUM(d.SubTotal) "
    "AS LineFpSubTotal, SUM(d.Tax) AS LineFpTax, MAX(d.DtlKey) AS LineFpMaxDtlKey, "
    "COUNT(d.FromDocDtlKey) AS LineFpLinked FROM {database}.dbo.DNDTL AS d WHERE d.DocKey "
    "= h.DocKey AND (d.SubTotal <> 0 OR d.Qty IS NOT NULL)) AS l"
)
_PRE35_DN_LINE = (
    "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey, d.Seq AS Seq, i.AutoKey AS "
    "ItemAutoKey, d.ItemCode AS ItemCode, d.Description AS Description, d.UOM AS UOM, "
    "d.Qty AS Qty, d.UnitPrice AS UnitPrice, d.DiscountAmt AS DiscountAmt, d.SubTotalExTax "
    "AS SubTotalExTax, d.TaxCode AS TaxCode, d.TaxRate AS TaxRate, d.Tax AS Tax, "
    "d.SubTotal AS SubTotal, d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, "
    "d.FromDocDtlKey AS FromDocDtlKey FROM {database}.dbo.DNDTL AS d LEFT JOIN "
    "{database}.dbo.Item AS i ON i.ItemCode = d.ItemCode WHERE d.DocKey = :doc_key AND "
    "(d.SubTotal <> 0 OR d.Qty IS NOT NULL)"
)
_PRE35_DN_FINGERPRINT = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineFpCount, SUM(d.Qty) AS LineFpQty, "
    "SUM(d.SubTotal) AS LineFpSubTotal, SUM(d.Tax) AS LineFpTax, MAX(d.DtlKey) AS "
    "LineFpMaxDtlKey, COUNT(d.FromDocDtlKey) AS LineFpLinked FROM {database}.dbo.DNDTL AS "
    "d JOIN {database}.dbo.DN AS h ON h.DocKey = d.DocKey WHERE h.DocDate >= :from_date "
    "AND (d.SubTotal <> 0 OR d.Qty IS NOT NULL) GROUP BY d.DocKey"
)
_PRE35_AR_HEADER = (
    "SELECT c.AutoKey AS DebtorKey, c.AccNo AS DebtorCode, s.TotalOutstanding AS "
    "TotalOutstanding, s.OpenCount AS OpenCount, s.LastModified AS LastModified FROM "
    "{database}.dbo.Debtor AS c JOIN (SELECT a.DebtorCode AS DebtorCode, SUM(a.Amount) AS "
    "TotalOutstanding, SUM(CASE WHEN a.Amount <> 0 THEN 1 ELSE 0 END) AS OpenCount, "
    "MAX(a.LastModified) AS LastModified FROM (SELECT i.DebtorCode AS DebtorCode, "
    "i.Outstanding AS Amount, COALESCE(i.LastModified, CAST('2000-01-01' AS datetime)) AS "
    "LastModified FROM {database}.dbo.ARInvoice AS i WHERE COALESCE(i.Cancelled, 'F') <> "
    "'T' UNION ALL SELECT n.DebtorCode, n.Outstanding, COALESCE(n.LastModified, "
    "CAST('2000-01-01' AS datetime)) FROM {database}.dbo.ARDN AS n UNION ALL SELECT "
    "r.DebtorCode, -(r.NetTotal - COALESCE(r.KnockOffAmt, 0)), COALESCE(r.LastModified, "
    "CAST('2000-01-01' AS datetime)) FROM {database}.dbo.ARCN AS r) AS a GROUP BY "
    "a.DebtorCode) AS s ON s.DebtorCode = c.AccNo"
)
_PRE35_AR_LINE = (
    "SELECT x.DocType AS DocType, x.BillingDocKey AS BillingDocKey, x.Outstanding AS "
    "Outstanding, x.DueDate AS DueDate FROM (SELECT CASE WHEN m.IvHits = 1 THEN 'IV' ELSE "
    "'CS' END AS DocType, CASE WHEN m.IvHits = 1 THEN m.IvKey ELSE m.CsKey END AS "
    "BillingDocKey, i.Outstanding AS Outstanding, i.DueDate AS DueDate, i.DebtorCode AS "
    "DebtorCode FROM {database}.dbo.ARInvoice AS i CROSS APPLY (SELECT (SELECT COUNT(*) "
    "FROM {database}.dbo.IV AS b WHERE b.DocNo = i.DocNo AND b.DebtorCode = i.DebtorCode) "
    "AS IvHits, (SELECT MIN(b.DocKey) FROM {database}.dbo.IV AS b WHERE b.DocNo = i.DocNo "
    "AND b.DebtorCode = i.DebtorCode) AS IvKey, (SELECT COUNT(*) FROM {database}.dbo.CS AS "
    "b WHERE b.DocNo = i.DocNo AND b.DebtorCode = i.DebtorCode) AS CsHits, (SELECT "
    "MIN(b.DocKey) FROM {database}.dbo.CS AS b WHERE b.DocNo = i.DocNo AND b.DebtorCode = "
    "i.DebtorCode) AS CsKey, (SELECT COUNT(*) FROM {database}.dbo.ARInvoice AS a2 WHERE "
    "a2.DocNo = i.DocNo AND a2.DebtorCode = i.DebtorCode) AS ArHits) AS m WHERE "
    "COALESCE(i.Cancelled, 'F') <> 'T' AND i.Outstanding <> 0 AND m.IvHits + m.CsHits = 1 "
    "AND m.ArHits = 1 UNION ALL SELECT 'DN', m.DnKey, n.Outstanding, n.DueDate, "
    "n.DebtorCode FROM {database}.dbo.ARDN AS n CROSS APPLY (SELECT (SELECT COUNT(*) FROM "
    "{database}.dbo.DN AS b WHERE b.DocNo = n.DocNo AND b.DebtorCode = n.DebtorCode) AS "
    "DnHits, (SELECT MIN(b.DocKey) FROM {database}.dbo.DN AS b WHERE b.DocNo = n.DocNo AND "
    "b.DebtorCode = n.DebtorCode) AS DnKey, (SELECT COUNT(*) FROM {database}.dbo.ARDN AS "
    "a2 WHERE a2.DocNo = n.DocNo AND a2.DebtorCode = n.DebtorCode) AS ArHits) AS m WHERE "
    "n.Outstanding <> 0 AND m.DnHits = 1 AND m.ArHits = 1 UNION ALL SELECT 'CN', m.CnKey, "
    "-(r.NetTotal - COALESCE(r.KnockOffAmt, 0)), NULL, r.DebtorCode FROM "
    "{database}.dbo.ARCN AS r CROSS APPLY (SELECT (SELECT COUNT(*) FROM {database}.dbo.CN "
    "AS b WHERE b.DocNo = r.DocNo AND b.DebtorCode = r.DebtorCode) AS CnHits, (SELECT "
    "MIN(b.DocKey) FROM {database}.dbo.CN AS b WHERE b.DocNo = r.DocNo AND b.DebtorCode = "
    "r.DebtorCode) AS CnKey, (SELECT COUNT(*) FROM {database}.dbo.ARCN AS a2 WHERE "
    "a2.DocNo = r.DocNo AND a2.DebtorCode = r.DebtorCode) AS ArHits) AS m WHERE r.NetTotal "
    "- COALESCE(r.KnockOffAmt, 0) <> 0 AND m.CnHits = 1 AND m.ArHits = 1) AS x JOIN "
    "{database}.dbo.Debtor AS c ON c.AccNo = x.DebtorCode WHERE c.AutoKey = :doc_key"
)
_PRE35_AR_FINGERPRINT = (
    "SELECT c.AutoKey AS DocKey, s.TotalOutstanding AS FpOutstanding, s.OpenCount AS "
    "FpOpenCount, s.LastModified AS FpLastModified FROM {database}.dbo.Debtor AS c JOIN "
    "(SELECT a.DebtorCode AS DebtorCode, SUM(a.Amount) AS TotalOutstanding, SUM(CASE WHEN "
    "a.Amount <> 0 THEN 1 ELSE 0 END) AS OpenCount, MAX(a.LastModified) AS LastModified "
    "FROM (SELECT i.DebtorCode AS DebtorCode, i.Outstanding AS Amount, "
    "COALESCE(i.LastModified, CAST('2000-01-01' AS datetime)) AS LastModified FROM "
    "{database}.dbo.ARInvoice AS i WHERE COALESCE(i.Cancelled, 'F') <> 'T' UNION ALL "
    "SELECT n.DebtorCode, n.Outstanding, COALESCE(n.LastModified, CAST('2000-01-01' AS "
    "datetime)) FROM {database}.dbo.ARDN AS n UNION ALL SELECT r.DebtorCode, -(r.NetTotal "
    "- COALESCE(r.KnockOffAmt, 0)), COALESCE(r.LastModified, CAST('2000-01-01' AS "
    "datetime)) FROM {database}.dbo.ARCN AS r) AS a GROUP BY a.DebtorCode) AS s ON "
    "s.DebtorCode = c.AccNo WHERE s.LastModified >= :from_date"
)

_BILLING_DRAFT_FILTER = 'DocStatus != "D"'
# The filter reads `DocStatus`: a header that no longer returns it (hand-edited
# after the CS "Invalid column" error) would fail every run on the filter.
_SELECTS_DOC_STATUS = re.compile(r"\bAS\s+DocStatus\b", re.IGNORECASE)
_BILLING_FILTER_ENTITY_TYPES = ("invoice", "cash_sale", "credit_note", "debit_note")
_BILLING_FROM_DOC_COLUMNS = ("FromDocType", "FromDocNo", "FromDocDtlKey")
_DN_FROM_DOC_CUTS = (
    ", l.LineFpLinked AS LineFpLinked",
    ", COUNT(d.FromDocDtlKey) AS LineFpLinked",
    ", d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, d.FromDocDtlKey AS FromDocDtlKey",
)
_AR_CANCEL_FIXES = (
    ("FROM {database}.dbo.ARDN AS n UNION ALL",
     "FROM {database}.dbo.ARDN AS n WHERE COALESCE(n.Cancelled, 'F') <> 'T' UNION ALL"),
    ("FROM {database}.dbo.ARCN AS r)",
     "FROM {database}.dbo.ARCN AS r WHERE COALESCE(r.Cancelled, 'F') <> 'T')"),
    ("WHERE n.Outstanding <> 0 AND",
     "WHERE COALESCE(n.Cancelled, 'F') <> 'T' AND n.Outstanding <> 0 AND"),
    ("WHERE r.NetTotal - COALESCE(r.KnockOffAmt, 0) <> 0 AND",
     "WHERE COALESCE(r.Cancelled, 'F') <> 'T' AND r.NetTotal - COALESCE(r.KnockOffAmt, 0) <> 0 AND"),
)


def _p35_rewrite(text: str, pairs) -> str:
    for old, new in pairs:
        text = text.replace(old, new)
    return text


_PRE35_BILLING_TEXTS: Dict[str, Dict[str, str]] = {
    "invoice": {"lineQuery": _NEW_BILLING_DO_LINE_QUERIES["invoice"]},
    "cash_sale": {
        "query": _PRE35_CS_HEADER, "lineQuery": _NEW_BILLING_DO_LINE_QUERIES["cash_sale"],
    },
    "debit_note": {
        "query": _PRE35_DN_HEADER, "lineQuery": _PRE35_DN_LINE,
        "fingerprintQuery": _PRE35_DN_FINGERPRINT,
    },
    "ar_outstanding": {
        "query": _PRE35_AR_HEADER, "lineQuery": _PRE35_AR_LINE,
        "fingerprintQuery": _PRE35_AR_FINGERPRINT,
    },
}
_POST35_BILLING_TEXTS: Dict[str, Dict[str, str]] = {
    "invoice": {"lineQuery": _OLD_BILLING_DO_LINE_QUERIES["invoice"]},
    "cash_sale": {
        "query": _PRE35_CS_HEADER.replace("h.DocStatus AS DocStatus", "NULL AS DocStatus", 1),
        "lineQuery": _OLD_BILLING_DO_LINE_QUERIES["cash_sale"],
    },
    "debit_note": {
        key: _p35_rewrite(text, [(cut, "") for cut in _DN_FROM_DOC_CUTS])
        for key, text in _PRE35_BILLING_TEXTS["debit_note"].items()
    },
    "ar_outstanding": {
        key: _p35_rewrite(text, _AR_CANCEL_FIXES)
        for key, text in _PRE35_BILLING_TEXTS["ar_outstanding"].items()
    },
}


def backfill_billing_preset_fix(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA, tenant_id: Optional[str] = None,
) -> int:
    """Plan 35 (lane SS-BILLING-PRESET-FIX) - move every existing billing /
    AR task onto the preset fixed against the real AutoCount schema. Returns
    the number of changes made (tasks rewritten + mapping rows changed); 0 on
    a schema that predates the columns this touches.

    Per task and per stored query (``query`` / ``lineQuery`` /
    ``fingerprintQuery``): byte-identical to the company's substitution of
    the frozen pre-plan-35 text -> the frozen new text; already new, or
    blank, -> skipped silently; anything else is customised: left untouched,
    one WARNING naming the config id. Each query stands on its own.

    Riding along with a rewrite (an enabled row on an unselected column 422s
    the next Mapping-tab save):
    * IV/CS ``lineQuery`` (the DODTL join is back): ``LinkDODocKey`` rejoins
      ``line_result_columns`` and its line row is enabled (0032 disabled it),
      or created when the task was seeded after 0032;
    * DN ``query``: ``LineFpLinked`` leaves ``result_columns``; DN
      ``lineQuery``: the ``FromDoc*`` columns leave ``line_result_columns``
      and their enabled line rows are disabled.
    NULL column lists (never previewed) stay NULL.

    A blank ``filterFormula`` on an IV/CS/CN/DN task becomes the draft
    filter when its header returns ``DocStatus`` (the stored ``query``
    selects it, or Preview saw it in ``result_columns``); otherwise, and for
    a hand-written filter, it is left with one WARNING.

    ``tenant_id`` (``update_tenant``) scopes the pass; ``None`` (the deploy
    migration) covers every tenant. Frozen ``sa.table`` only, company
    resolved WITH the config's own ``tenant_id``. Does not commit.
    """
    needed = {
        "ac_entity_config": _CONSIGNMENT_BACKFILL_ENTITY_CONFIG_COLUMNS,
        "ac_company": _CONSIGNMENT_BACKFILL_COMPANY_COLUMNS,
        "ac_field_mapping": _CONSIGNMENT_BACKFILL_FIELD_MAPPING_COLUMNS,
    }
    for table, columns in needed.items():
        have = existing_columns(bind, table, schema=schema)
        if have is None or not columns <= have:
            return 0

    entity_config = sa.table(
        "ac_entity_config",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("source_config", sa.JSON(none_as_null=True)),
        sa.column("result_columns", sa.JSON(none_as_null=True)),
        sa.column("line_result_columns", sa.JSON(none_as_null=True)),
        schema=schema,
    )
    company_table = sa.table(
        "ac_company",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("database_name", sa.String),
        schema=schema,
    )
    field_mapping = sa.table(
        "ac_field_mapping",
        sa.column("id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("source_path", sa.String),
        sa.column("canonical_field", sa.String),
        sa.column("transform", sa.String),
        sa.column("formula", sa.Text),
        sa.column("is_required", sa.Boolean),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_source_owned", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        schema=schema,
    )

    connectable = bind.connection() if hasattr(bind, "get_bind") else bind
    entity_types = sorted(set(_BILLING_FILTER_ENTITY_TYPES) | set(_PRE35_BILLING_TEXTS))
    select_configs = sa.select(
        entity_config.c.id, entity_config.c.tenant_id, entity_config.c.company_id,
        entity_config.c.entity_type, entity_config.c.source_config,
        entity_config.c.result_columns, entity_config.c.line_result_columns,
    ).where(entity_config.c.entity_type.in_(entity_types))
    if tenant_id is not None:
        select_configs = select_configs.where(entity_config.c.tenant_id == tenant_id)
    configs = connectable.execute(select_configs).fetchall()

    def line_rows(config_tenant_id: str, company_id: str, entity_type: str, source_path: str):
        return (
            field_mapping.c.tenant_id == config_tenant_id,
            field_mapping.c.company_id == company_id,
            field_mapping.c.entity_type == entity_type,
            field_mapping.c.scope == SCOPE_LINE,
            field_mapping.c.source_path == source_path,
        )

    touched = 0
    for (
        config_id, config_tenant_id, company_id, entity_type, source_config,
        result_columns, line_columns,
    ) in configs:
        company_row = connectable.execute(
            sa.select(company_table.c.database_name).where(
                company_table.c.id == company_id,
                company_table.c.tenant_id == config_tenant_id,
            )
        ).first()
        if company_row is None or not company_row[0]:
            continue
        database_name = company_row[0]
        fresh = dict(source_config or {})
        rewritten = set()
        for key, old_template in _PRE35_BILLING_TEXTS.get(entity_type, {}).items():
            stored = fresh.get(key)
            old = old_template.replace("{database}", database_name)
            new = _POST35_BILLING_TEXTS[entity_type][key].replace("{database}", database_name)
            if stored == old:
                fresh[key] = new
                rewritten.add(key)
            elif stored and stored != new:
                logger.warning(
                    "Billing task %s (%s) has a %s the plan-35 backfill does not recognise "
                    "as the AutoCount preset - left untouched. Compare it with the preset "
                    "(Mapping tab, Use preset): CS has no DocStatus, DNDTL has no FromDoc* "
                    "columns, cancelled ARDN/ARCN rows are excluded, and IV/CS lines join "
                    "DODTL for the DO line.",
                    config_id, entity_type, key,
                )
        filter_changed = False
        if entity_type in _BILLING_FILTER_ENTITY_TYPES:
            stored_filter = str(fresh.get("filterFormula") or "").strip()
            has_status = bool(_SELECTS_DOC_STATUS.search(str(fresh.get("query") or ""))) or (
                "DocStatus" in [str(c) for c in (result_columns or [])]
            )
            if not stored_filter and has_status:
                fresh["filterFormula"] = _BILLING_DRAFT_FILTER
                filter_changed = True
            elif not stored_filter:
                logger.warning(
                    "Billing task %s (%s) has a header query that returns no DocStatus "
                    "column - no draft filter set. Select DocStatus (NULL AS DocStatus on "
                    "CS) and set the filter %s so AutoCount drafts are not pushed as posted.",
                    config_id, entity_type, _BILLING_DRAFT_FILTER,
                )
            elif stored_filter != _BILLING_DRAFT_FILTER:
                logger.warning(
                    "Billing task %s (%s) has its own filter formula - left untouched. "
                    "Make sure it also drops AutoCount drafts (%s).",
                    config_id, entity_type, _BILLING_DRAFT_FILTER,
                )
        if not rewritten and not filter_changed:
            continue

        header_list = None if result_columns is None else [str(c) for c in result_columns]
        line_list = None if line_columns is None else [str(c) for c in line_columns]
        if entity_type in ("invoice", "cash_sale") and "lineQuery" in rewritten:
            if line_list is not None and "LinkDODocKey" not in line_list:
                line_list.append("LinkDODocKey")
            # Any row on the target (uq_ac_field_mapping is on canonical_field):
            # one pointed at another column is the operator's and stays.
            has_row = connectable.execute(
                sa.select(field_mapping.c.id).where(
                    field_mapping.c.tenant_id == config_tenant_id,
                    field_mapping.c.company_id == company_id,
                    field_mapping.c.entity_type == entity_type,
                    field_mapping.c.scope == SCOPE_LINE,
                    field_mapping.c.canonical_field == "link_do_doc_key",
                )
            ).first() is not None
            if has_row:
                enabled = connectable.execute(
                    sa.update(field_mapping)
                    .where(
                        *line_rows(config_tenant_id, company_id, entity_type, "LinkDODocKey"),
                        field_mapping.c.is_enabled.is_(False),
                    )
                    .values(is_enabled=True)
                )
                touched += enabled.rowcount or 0
            else:
                sort_order = connectable.execute(
                    sa.select(sa.func.count())
                    .select_from(field_mapping)
                    .where(
                        field_mapping.c.tenant_id == config_tenant_id,
                        field_mapping.c.company_id == company_id,
                        field_mapping.c.entity_type == entity_type,
                        field_mapping.c.scope == SCOPE_LINE,
                    )
                ).scalar() or 0
                connectable.execute(
                    sa.insert(field_mapping).values(
                        id=str(uuid.uuid4()),
                        tenant_id=config_tenant_id,
                        company_id=company_id,
                        entity_type=entity_type,
                        scope=SCOPE_LINE,
                        source_path="LinkDODocKey",
                        canonical_field="link_do_doc_key",
                        transform="int",
                        formula=None,
                        is_required=False,
                        is_enabled=True,
                        is_source_owned=True,
                        sort_order=sort_order,
                    )
                )
                touched += 1
        if entity_type == "debit_note":
            if "query" in rewritten and header_list is not None:
                header_list = [c for c in header_list if c != "LineFpLinked"]
            if "lineQuery" in rewritten:
                if line_list is not None:
                    line_list = [c for c in line_list if c not in _BILLING_FROM_DOC_COLUMNS]
                for column in _BILLING_FROM_DOC_COLUMNS:
                    disabled = connectable.execute(
                        sa.update(field_mapping)
                        .where(
                            *line_rows(config_tenant_id, company_id, entity_type, column),
                            field_mapping.c.is_enabled.is_(True),
                        )
                        .values(is_enabled=False)
                    )
                    touched += disabled.rowcount or 0
        connectable.execute(
            sa.update(entity_config)
            .where(entity_config.c.id == config_id)
            .values(
                source_config=fresh,
                result_columns=header_list,
                line_result_columns=line_list,
            )
        )
        touched += 1
    return touched

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

from typing import Any, Dict, Optional

import sqlalchemy as sa

from .canonical.documents import is_document_entity
from .db import AUTOCOUNT_SCHEMA
from .envelopes import ENVELOPE_STATUS_DICT
from .mapping import DOCUMENT_LINE_FIXED_FIELDS, SCOPE_LINE
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
# UPDATE - the natural unit is an ORM insert. A live-Postgres Alembic
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
    _strip_picker_keys_and_flush(db, config, source_config)
    return created


def _strip_picker_keys_and_flush(db: Any, config: Any, source_config: Dict[str, Any]) -> None:
    stripped = {
        k: v for k, v in source_config.items()
        if k not in ("lineKeyColumn", "lineProductColumn", "lineWarehouseColumn")
    }
    if stripped != source_config:
        config.source_config = stripped

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
    config = (
        db.query(AcEntityConfig)
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

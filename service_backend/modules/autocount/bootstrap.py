"""AutoCount bootstrap - the App-Store module contract (plan 08 §4, AC-13-45).

``install`` is GLOBAL and idempotent (schema + tables + permission-catalog sync);
the per-tenant hooks (``install_tenant`` / ``update_tenant`` / ``uninstall_tenant``)
are driven by AppStoreService when a tenant installs/updates/uninstalls.
Permission GRANTS are the store's concern - it grants the module keys to the
tenant's Admin role at install, which is why a brand-new module needs no grant
sweep for existing tenants (nobody has it installed yet).

Stage 1 scaffold: schema + (currently empty) tables + permission CSV + the
integration provider. Companies, watermarks, entity config, staging and the sync
job handler are filled in by later slices - the hooks are wired now so the
module contract is complete from day one.
"""
from pathlib import Path
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover - typing only, core never imported at runtime here
    from app.models.background_job import BackgroundJob

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register module tables on AutocountBase.metadata
from .db import AUTOCOUNT_SCHEMA, AutocountBase

MODULE_NAME = "autocount"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def _evict_deleted_connection(session: Session, ev: Dict[str, Any]) -> None:
    """CRUD event-bus subscriber (S6 merge-gate review SHOULD-FIX 4).

    ``sql_source.runtime.SqlSourceRuntime.evict`` existed with no production
    caller: deleting a ``sql_database`` connection left its cached engine (up
    to 5 live pooled sessions to the CUSTOMER's own database) and its
    ``SCHEMA_CACHE`` entry alive until the process restarted. There is no
    core connection-deleted hook to import into (core must never import a
    module) - but the core CRUD event bus already emits ``connection``/
    ``deleted`` on every delete (``IntegrationService.delete``), so this
    registers as an ordinary subscriber (``register_event_subscriber``,
    plan sprint-2/10 D5 - the audit-log seam, generic to any consumer) at
    boot instead of a bespoke hook. Runs for EVERY connection delete, any
    provider - harmless no-op when the id was never a SQL-source engine
    (nothing cached for it).
    """
    if ev.get("entity_type") != "connection" or ev.get("action") != "deleted":
        return
    connection_id = ev.get("record_id")
    if not connection_id:
        return
    from .sql_source.introspect import SCHEMA_CACHE
    from .sql_source.runtime import RUNTIME

    RUNTIME.evict(connection_id)
    tenant_id = ev.get("tenant_id")
    if tenant_id:
        SCHEMA_CACHE.invalidate(f"{tenant_id}:{connection_id}")


def register_capabilities() -> None:
    """Boot-time capability registration (sprint-3/10 D5). Idempotent.

    AutoCount provides no cross-module capability yet. The read pipeline exposes
    its canonical records to consumers over the public gateway, not the in-process
    capability seam, so this stays a no-op unless a sibling module needs a direct
    call."""
    return None


def register_engine_entities() -> None:
    """Boot-time registration into shared CORE registries (plan 11 D9).

    Idempotent - ``register_module_boot`` calls this on every boot/bootstrap, and
    the provider registry is a keyed dict (re-registering replaces in place).

    Registers:
      * the AutoCount ``erp`` connection provider, so it appears in
        ``GET /integrations/providers`` and is configurable from the standard
        integrations surface (AC-13-01);
      * the ``autocount_sync`` background-job handler.

    The job handler must be registered in EVERY process that touches a sync job:
    the API process creates jobs (``JobService.create`` validates the type is
    registered) and - under eager dev/test - runs them inline. The Celery worker
    boots no FastAPI lifespan, so it gets the handler from an explicit import in
    ``app/workflow_engine/worker.py`` instead. Missing EITHER path leaves jobs
    Pending forever with no error.

    Status entities, importer defs and terminology land with the entities they
    describe in later slices.
    """
    from app.integrations import register_provider
    from app.workflow_engine.entity_events import register_event_subscriber

    from .provider import AutoCountProvider
    from .sorento_provider import SorentoProvider
    from .sql_provider import SqlDatabaseProvider
    from .sync import register_autocount_sync_handler

    register_provider(AutoCountProvider())
    # The OUTBOUND consumer target (hop 2). Registered beside the inbound ``erp``
    # provider so the Sorento connection is configured from the same
    # `/settings/integrations` surface (AC-14-15).
    register_provider(SorentoProvider())
    # The direct-DB read-only source (plan 22, AC-22-01) - a second ``erp``
    # provider, configured from the same surface.
    register_provider(SqlDatabaseProvider())
    register_autocount_sync_handler()
    # S6 review SHOULD-FIX 4 - drop the cached engine + schema cache the
    # instant a ``sql_database`` connection is deleted (see the subscriber's
    # own docstring). Idempotent (the bus dedupes by function identity).
    register_event_subscriber(_evict_deleted_connection)

    # Deferred (grace-window) actions (sprint-5/07 review round): "Re-push
    # all" registers into the CORE grace-window engine here, the same way
    # `omnichannel`/`ideation` extend it - never a fork.
    from .deferred_actions import register_autocount_deferred_actions

    register_autocount_deferred_actions()


def create_schema_and_tables(engine: Engine) -> None:
    """Create the module schema (Postgres) + all module tables. Idempotent."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{AUTOCOUNT_SCHEMA}"'))
    AutocountBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    """Global install (plan 08 §4): schema + tables + permission catalog sync.

    Runs at every bootstrap (idempotent). Per-tenant seeding happens in
    ``install_tenant`` when a tenant actually installs the module.
    """
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    """Per-tenant seed (plan 08 §4). Idempotent.

    Still nothing to seed: a tenant's AutoCount footprint begins when an
    operator registers a COMPANY, and a company cannot exist before its
    connection does. Per-company entity configs + mapping rows are seeded by
    ``CompanyService.seed_company_defaults`` at that moment - seeding them here
    would mean guessing a company that has not been discovered yet."""
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    """Per-tenant data migration between provisioned versions (plan 08 D3).

    **0.1.0 → 0.2.0 (masters).** Two things existing tenants need, and neither is
    delivered by seeding new rows:

    1. **Entity configs + mapping rows for the two master entities on every
       company that ALREADY EXISTS.** ``seed_company_defaults`` runs once, when a
       company is registered - a company registered under 0.1.0 was seeded with
       GRN only, so without this pass the operator sees no Supplier/Customer
       entity at all and the feature is silently invisible to exactly the tenants
       who already use the module. Re-running the seed is safe: every branch in
       it is seed-if-absent, so a company's existing config and any operator
       edits to its mapping rows are untouched.

    2. **Envelope / initial-load values on pre-existing ``ac_entity_config``
       rows.** Module Alembic fills these, but a host built with ``init_db``
       (``create_all`` + seed) never runs module Alembic - and ``create_all``
       cannot ALTER an existing table, so those rows can sit empty against
       columns the code assumes are populated. Cheap, idempotent, and the
       difference between a working sync and an ``UnknownEnvelope`` at fetch
       time.
    """
    from .backfill import (
        backfill_db_company_entity_sources,
        backfill_disable_credit_limit_mapping_rows,
        backfill_document_fingerprint_queries,
        backfill_document_line_linkage,
        backfill_entity_config_defaults,
        backfill_etl_defaults,
        backfill_sales_order_ref,
        backfill_shipping_order_container_number,
        backfill_sink_impl_defaults,
        default_schema,
    )
    from .repositories import CompanyRepository
    from .services.company_service import CompanyService

    schema = default_schema(db.get_bind())
    backfill_entity_config_defaults(db, schema=schema)
    # A company registered before the sink columns existed must land on the
    # ``'logging'`` no-op (its pre-hop-2 behaviour), not sit NULL against a
    # NOT NULL column on a create_all-first host.
    backfill_sink_impl_defaults(db, schema=schema)
    # 0.3.0 → plan 22: every pre-existing task/staged/run row gets its ETL
    # defaults (draft / upsert / manual) on a create_all-first host too.
    backfill_etl_defaults(db, schema=schema)
    # sprint-5/04 (Sorento contract 2.1): an ENABLED customer row saved before
    # ``credit_limit`` left ``CanonicalCustomer.SINK_FIELDS`` is a dead row
    # (mapped, never sent). Disable it so the table matches the accepted
    # target set. Module Alembic 0013 does the same on deploy; this covers the
    # App Store 0.4.0 -> 0.5.0 update path (idempotent either way).
    backfill_disable_credit_limit_mapping_rows(db, schema=schema)
    # 0.5.0 -> 0.6.0 (prod incident 2026-09-06): a DATABASE company's stranded
    # never-run ``autocount_read`` rows (the old seed ran on every company) are
    # pointed at ``sql_db`` BEFORE the seed loop below - which now returns
    # early for a DB company (D13: born empty), so this upgrade and every
    # later one stop seeding onto one. Module Alembic 0014 runs the same
    # sweep on deploy.
    backfill_db_company_entity_sources(db, schema=schema)
    # 0.6.0 -> feat/spo-container-number: Sorento held 68,519 SPO allocations
    # with no container because the SPO task's header query never selected
    # AutoCount `PO.Ref`. Module Alembic 0016 runs the same repair on deploy.
    backfill_shipping_order_container_number(db, schema=schema)
    # 0.6.1 -> feat/line-fingerprint-sweep: every document task lacking a
    # fingerprintQuery gets the preset's own sweep query. Module Alembic
    # 0017 runs the same repair on deploy.
    backfill_document_fingerprint_queries(db, schema=schema)
    # 0.7.0 -> 0.8.0 (sprint-5/06 S2): every existing PO/SPO task gets the
    # six FromSO*/FromPO* line mapping rows, and a byte-identical old
    # statement is rewritten to the NEW preset text carrying line linkage.
    # Module Alembic 0018 runs the same repair on deploy.
    backfill_document_line_linkage(db, schema=schema)
    # 0.8.0 -> sprint-5/07: every existing `sales_order` task gets a
    # `Ref -> ref` header mapping row (enabled when the query already selects
    # `Ref`, disabled + one warning otherwise), and a byte-identical old
    # preset query is rewritten to the NEW text carrying `h.Ref AS Ref`.
    # Module Alembic 0019 runs the same repair on deploy.
    backfill_sales_order_ref(db, schema=schema)

    service = CompanyService(db)
    page = 0
    while True:
        companies, total = CompanyRepository(db).list(tenant_id, page=page, page_size=50)
        if not companies:
            break
        for company in companies:
            service.seed_company_defaults(tenant_id, company.id)
        page += 1
        if (page * 50) >= total:
            break
    db.flush()


def on_job_orphaned(
    db: Session, job: "BackgroundJob", *, now: Optional[datetime] = None
) -> None:
    """Core's orphan sweep (``JobService.fail_orphaned_running_jobs``) just
    failed ``job``; close THIS module's bookkeeping for it.

    Only an ``autocount_sync`` job is ours. Its open ``ac_sync_run`` row(s)
    (``job_id`` match, ``finished_at IS NULL``) get ``outcome=FAILED``, the
    same "Interrupted" error, ``finished_at`` and a ``duration_ms`` from their
    own ``started_at`` - the Runs list then shows what happened instead of a
    run that is forever in progress. Staged rows are deliberately untouched:
    the watermark HELD, so the next run re-reads the window and re-offers
    them (prod incident 2026-09-07, PO sync killed by a deploy drain). No
    commit here - the sweep owns the transaction.
    """
    from .models import RUN_FAILED, AcSyncRun
    from .sync import AUTOCOUNT_SYNC

    if getattr(job, "type", None) != AUTOCOUNT_SYNC:
        return
    # The sweep's own clock, so the run's ``finished_at`` equals the job's.
    now = now or datetime.now(timezone.utc)
    open_runs = (
        db.query(AcSyncRun)
        .filter(
            AcSyncRun.tenant_id == job.tenant_id,
            AcSyncRun.job_id == job.id,
            AcSyncRun.finished_at.is_(None),
        )
        .all()
    )
    for run in open_runs:
        run.outcome = RUN_FAILED
        run.error = getattr(job, "error", None) or "Interrupted: the worker stopped before this run finished."
        run.finished_at = now
        started = run.started_at
        run.duration_ms = int((now - started).total_seconds() * 1000) if started else 0
    db.flush()


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe THIS tenant's rows from every module table (plan 08 §5).

    The module schema and other tenants' rows are untouched - uninstall is
    per-tenant, never global. Reverse dependency order avoids FK violations.
    (No module tables in the scaffold slice - a safe no-op that automatically
    covers every table added later.)"""
    for table in reversed(AutocountBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    """Backfill detection (loader) for pre-App-Store installs. AutoCount is a
    net-new module - no legacy data ever existed - so no tenant backfills."""
    return False

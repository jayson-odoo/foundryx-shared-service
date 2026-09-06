"""A DATABASE company's entity configs must be born (and repaired) as ``sql_db``.

Prod, 2026-09-06: a company whose source connection is a ``sql_database``
connection (``source_kind() == 'db'``) ended up with Customer/Supplier/GRN
entity configs at ``source_impl="autocount_read"`` because
``CompanyService.seed_company_defaults`` hardcodes that value - and the
entities list hides "Change source" on a DB company, so the operator had no
way out.

Decision (D13 wins): a DB company is born EMPTY and stays empty until the
operator adds entities - the upgrade path must never seed onto it.

(1) ``seed_company_defaults`` on a DB company adds NO entity configs and NO
    mapping rows (an API company still gets its ``autocount_read`` seed -
    control).
(2) ``backfill_db_company_entity_sources`` repairs existing rows: every
    ``autocount_read`` config on a DB company that has NEVER RUN flips to
    ``sql_db``; a config that has run (``ac_entity_config.last_run_at`` set,
    OR a watermark row with ``last_modified_at`` set - either marker) is left
    alone; idempotent; tolerant of a bind with none of the tables.
(3) ``update_tenant`` repairs the stranded row and seeds NOTHING onto a DB
    company; an empty DB company is still empty afterwards.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from modules.autocount.models import (
    SOURCE_IMPL_AUTOCOUNT_READ,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcWatermark,
)
from modules.autocount.services.company_service import SEEDED_ENTITIES, CompanyService


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db, provider: str, config: dict, *, name: str) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=provider, type="erp", name=name,
        config_json=config, credentials_json=encrypt_secret({"password": "pw"}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _sql_connection(db, *, database: str) -> Connection:
    return _connection(
        db, "sql_database",
        {"dbType": "postgresql", "host": "db.example.com", "port": "5432",
         "database": database, "username": "readonly"},
        name=f"sql {database}",
    )


def _api_connection(db, *, database: str) -> Connection:
    return _connection(
        db, "autocount",
        {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        name=f"api {database}",
    )


def _company(db, conn: Connection, *, database: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=database,
        company_name=database, name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(db, company: AcCompany, entity_type: str, *, source_impl: str) -> AcEntityConfig:
    row = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl=source_impl,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mark_run_by_last_run_at(db, config: AcEntityConfig) -> None:
    config.last_run_at = datetime.now(timezone.utc)
    db.commit()


def _mark_run_by_watermark(db, config: AcEntityConfig) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        AcWatermark(
            tenant_id=config.tenant_id, company_id=config.company_id,
            entity_type=config.entity_type, last_modified_at=now,
            last_success_at=now, last_attempt_at=now,
        )
    )
    db.commit()


def _mapping_count(db, company_id: str) -> int:
    return (
        db.query(AcFieldMapping)
        .filter(AcFieldMapping.tenant_id == DEFAULT_TENANT_ID, AcFieldMapping.company_id == company_id)
        .count()
    )


def _source_impls(db, company_id: str) -> dict:
    rows = (
        db.query(AcEntityConfig)
        .filter(AcEntityConfig.tenant_id == DEFAULT_TENANT_ID, AcEntityConfig.company_id == company_id)
        .all()
    )
    return {r.entity_type: r.source_impl for r in rows}


# ── (1) the seed is API-shaped and never lands on a DB company (D13) ───────


def test_seed_company_defaults_adds_nothing_to_a_database_company(db):
    """A DB company is born empty and stays empty until the operator adds
    entities: no configs, no mapping rows."""
    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")

    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    assert _source_impls(db, company.id) == {}
    assert _mapping_count(db, company.id) == 0


def test_seed_company_defaults_leaves_a_database_companys_existing_rows_untouched(db):
    """Returning without adding must also mean returning without touching:
    an operator-added sql_db entity survives the seed byte-for-byte."""
    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    existing = _config(db, company, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_SQL_DB)

    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.expire_all()

    assert _source_impls(db, company.id) == {ENTITY_CUSTOMER: SOURCE_IMPL_SQL_DB}
    assert db.get(AcEntityConfig, existing.id).source_impl == SOURCE_IMPL_SQL_DB
    assert _mapping_count(db, company.id) == 0


def test_seed_company_defaults_keeps_autocount_read_on_an_api_company(db):
    """Control: the vendor-API company is exactly as plan 13 births it."""
    company = _company(db, _api_connection(db, database="AED_API"), database="AED_API")

    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    impls = _source_impls(db, company.id)
    assert set(impls) == set(SEEDED_ENTITIES)
    assert impls == {entity: SOURCE_IMPL_AUTOCOUNT_READ for entity in SEEDED_ENTITIES}
    assert _mapping_count(db, company.id) > 0


# ── (2) the backfill repairs existing rows ──────────────────────────────────


def test_backfill_flips_never_run_autocount_read_configs_on_database_companies_only(db):
    from modules.autocount.backfill import backfill_db_company_entity_sources

    db_company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    api_company = _company(db, _api_connection(db, database="AED_API"), database="AED_API")
    for entity in SEEDED_ENTITIES:
        _config(db, db_company, entity, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
        _config(db, api_company, entity, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)

    touched = backfill_db_company_entity_sources(db, schema=None)
    db.commit()
    db.expire_all()

    # Two masters flipped + the GRN row deleted (GRN has no database task).
    assert touched == len(SEEDED_ENTITIES)
    assert _source_impls(db, db_company.id) == {
        ENTITY_SUPPLIER: SOURCE_IMPL_SQL_DB, ENTITY_CUSTOMER: SOURCE_IMPL_SQL_DB
    }
    assert _source_impls(db, api_company.id) == {
        e: SOURCE_IMPL_AUTOCOUNT_READ for e in SEEDED_ENTITIES
    }

    # Idempotent: nothing left to repair.
    assert backfill_db_company_entity_sources(db, schema=None) == 0


def test_backfill_leaves_a_config_that_has_already_run_untouched(db):
    """A row that has synced under ``autocount_read`` carries state that
    belongs to that source; flipping it silently would be a different bug.
    EITHER marker means it ran: the config's own ``last_run_at``, or a
    watermark row with ``last_modified_at``. Only the never-run rows (the
    prod shape) are repaired, and an already-``sql_db`` row is not counted."""
    from modules.autocount.backfill import backfill_db_company_entity_sources

    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    ran_by_last_run = _config(db, company, ENTITY_SUPPLIER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _mark_run_by_last_run_at(db, ran_by_last_run)
    ran_by_watermark = _config(db, company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _mark_run_by_watermark(db, ran_by_watermark)
    fresh = _config(db, company, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    already = _config(db, company, "product", source_impl=SOURCE_IMPL_SQL_DB)

    touched = backfill_db_company_entity_sources(db, schema=None)
    db.commit()
    db.expire_all()

    assert touched == 1
    assert db.get(AcEntityConfig, ran_by_last_run.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
    assert db.get(AcEntityConfig, ran_by_watermark.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
    assert db.get(AcEntityConfig, fresh.id).source_impl == SOURCE_IMPL_SQL_DB
    assert db.get(AcEntityConfig, already.id).source_impl == SOURCE_IMPL_SQL_DB


def test_backfill_tolerates_a_bind_with_none_of_the_tables():
    """Same tolerance contract as every other helper in ``backfill.py`` (prod
    incident 2026-09-06): at a stamp that predates the tables it returns 0
    instead of raising."""
    from modules.autocount.backfill import backfill_db_company_entity_sources

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        assert backfill_db_company_entity_sources(conn, schema=None) == 0


# ── (3) delivered by update_tenant ──────────────────────────────────────────


def test_update_tenant_repairs_the_stranded_row_and_seeds_nothing_onto_a_database_company(db):
    """The composed path an existing host actually runs on a version bump
    (this is how prod got its stranded rows: the seed ran over EVERY company).
    The stranded never-run ``autocount_read`` row is repaired to ``sql_db``,
    no new configs or mapping rows appear, nothing is left at
    ``autocount_read`` - read back before any commit."""
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    stranded = _config(db, company, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    stranded_id = stranded.id
    configs_before = len(_source_impls(db, company.id))
    mappings_before = _mapping_count(db, company.id)
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.5.0")

    impls = _source_impls(db, company.id)
    assert db.get(AcEntityConfig, stranded_id).source_impl == SOURCE_IMPL_SQL_DB
    assert len(impls) == configs_before == 1
    assert _mapping_count(db, company.id) == mappings_before
    assert SOURCE_IMPL_AUTOCOUNT_READ not in impls.values()


def test_update_tenant_leaves_an_empty_database_company_empty(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, _sql_connection(db, database="AED_EMPTY"), database="AED_EMPTY")

    update_tenant(db, DEFAULT_TENANT_ID, "0.5.0")

    assert _source_impls(db, company.id) == {}
    assert _mapping_count(db, company.id) == 0


def test_update_tenant_still_seeds_an_api_company(db):
    """Control: the API company keeps the upgrade seed it has always had."""
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, _api_connection(db, database="AED_API"), database="AED_API")

    update_tenant(db, DEFAULT_TENANT_ID, "0.5.0")

    impls = _source_impls(db, company.id)
    assert impls == {entity: SOURCE_IMPL_AUTOCOUNT_READ for entity in SEEDED_ENTITIES}
    assert _mapping_count(db, company.id) > 0


# ═══════════════════════════════════════════════════════════════════════════
#  Review round 1 (7506781f)
# ═══════════════════════════════════════════════════════════════════════════

from modules.autocount.models import AcFieldMapping as _AcFieldMapping  # noqa: E402

TENANT_B = "tenant-b-seed-source"


def _tenant_b(db) -> None:
    from app.models.tenant import Tenant

    if db.get(Tenant, TENANT_B) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=TENANT_B, slug="tenant-b-seed-source", name="Tenant B",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _connection_for(db, tenant_id: str, provider: str, *, database: str) -> Connection:
    config = (
        {"dbType": "postgresql", "host": "db.example.com", "port": "5432",
         "database": database, "username": "readonly"}
        if provider == "sql_database"
        else {"baseUrl": "https://ac.example.com", "userId": "ADMIN"}
    )
    conn = Connection(
        tenant_id=tenant_id, provider=provider, type="erp", name=f"{provider} {database}",
        config_json=config, credentials_json=encrypt_secret({"password": "pw"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company_for(db, tenant_id: str, conn: Connection, *, database: str) -> AcCompany:
    company = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name=database,
        company_name=database, name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config_for(db, tenant_id: str, company_id: str, entity_type: str, *, source_impl: str) -> AcEntityConfig:
    row = AcEntityConfig(
        tenant_id=tenant_id, company_id=company_id, entity_type=entity_type, source_impl=source_impl,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _grn_mapping_rows(db, tenant_id: str, company_id: str, n: int = 2) -> None:
    for i in range(n):
        db.add(
            _AcFieldMapping(
                tenant_id=tenant_id, company_id=company_id, entity_type=ENTITY_GOODS_RECEIVED_NOTE,
                scope="header", source_path=f"Field{i}", canonical_field=f"field_{i}",
                transform="string", is_required=False, is_enabled=True, sort_order=i,
            )
        )
    db.commit()


def _mapping_rows(db, tenant_id: str, company_id: str, entity_type: str) -> int:
    return (
        db.query(_AcFieldMapping)
        .filter(
            _AcFieldMapping.tenant_id == tenant_id,
            _AcFieldMapping.company_id == company_id,
            _AcFieldMapping.entity_type == entity_type,
        )
        .count()
    )


# ── (1) tenant scoping: never a bare id match ───────────────────────────────


def test_backfill_is_tenant_scoped_even_when_a_company_id_is_reused_across_tenants(db):
    """The polymorphic-target_id rule: a DB company in tenant A must not
    repair (or be judged by) a row that belongs to tenant B - even a tenant-B
    row that happens to carry tenant A's ``company_id``. Both joins (company
    -> connection, config -> company) must match on ``tenant_id``."""
    from modules.autocount.backfill import backfill_db_company_entity_sources

    _tenant_b(db)
    # Tenant A: a DB company with a stranded row - the one legitimate flip.
    a_conn = _connection_for(db, DEFAULT_TENANT_ID, "sql_database", database="AED_A")
    a_company = _company_for(db, DEFAULT_TENANT_ID, a_conn, database="AED_A")
    a_row = _config_for(db, DEFAULT_TENANT_ID, a_company.id, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    # Tenant B: its OWN DB company + stranded row - a legitimate flip too.
    b_conn = _connection_for(db, TENANT_B, "sql_database", database="AED_B")
    b_company = _company_for(db, TENANT_B, b_conn, database="AED_B")
    b_row = _config_for(db, TENANT_B, b_company.id, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    # Tenant B row that REUSES tenant A's company_id (no such company in B):
    # must be judged inside tenant B only, where that id is nobody's DB company.
    leaked = _config_for(db, TENANT_B, a_company.id, ENTITY_SUPPLIER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    # Tenant A API company whose connection id is reused by a tenant-B sql
    # connection: the company -> connection join must match tenant too.
    api_conn = _connection_for(db, DEFAULT_TENANT_ID, "autocount", database="AED_API")
    api_company = _company_for(db, DEFAULT_TENANT_ID, api_conn, database="AED_API")
    api_row = _config_for(db, DEFAULT_TENANT_ID, api_company.id, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    cross = Connection(
        id=api_conn.id + "-x", tenant_id=TENANT_B, provider="sql_database", type="erp",
        name="cross", config_json={"database": "X"}, credentials_json=encrypt_secret({}), is_active=True,
    )
    db.add(cross)
    db.commit()
    # Point the tenant-A API company at a connection id that exists as
    # sql_database ONLY in tenant B.
    api_company.connection_id = cross.id
    db.commit()

    touched = backfill_db_company_entity_sources(db, schema=None)
    db.commit()
    db.expire_all()

    assert touched == 2
    assert db.get(AcEntityConfig, a_row.id).source_impl == SOURCE_IMPL_SQL_DB
    assert db.get(AcEntityConfig, b_row.id).source_impl == SOURCE_IMPL_SQL_DB
    assert db.get(AcEntityConfig, leaked.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
    assert db.get(AcEntityConfig, api_row.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ


# ── (2) GRN on a DB company is DELETED, not flipped ─────────────────────────


def test_backfill_deletes_never_run_grn_on_a_database_company_and_flips_the_rest(db):
    """GRN has no database task - a flipped GRN row would show a dead
    "Configure database query". A never-run GRN config on a DB company (and
    its mapping rows) is removed; a GRN that has run stays; the API
    company's GRN is untouched; the return value counts flips + deletes."""
    from modules.autocount.backfill import backfill_db_company_entity_sources

    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    grn = _config(db, company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    grn_id = grn.id
    _grn_mapping_rows(db, DEFAULT_TENANT_ID, company.id)
    supplier = _config(db, company, ENTITY_SUPPLIER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)

    ran_company = _company(db, _sql_connection(db, database="AED_RAN"), database="AED_RAN")
    ran_grn = _config(db, ran_company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _mark_run_by_watermark(db, ran_grn)
    _grn_mapping_rows(db, DEFAULT_TENANT_ID, ran_company.id)

    api_company = _company(db, _api_connection(db, database="AED_API"), database="AED_API")
    api_grn = _config(db, api_company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _grn_mapping_rows(db, DEFAULT_TENANT_ID, api_company.id)

    touched = backfill_db_company_entity_sources(db, schema=None)
    db.commit()
    db.expire_all()

    assert touched == 2  # one flip (supplier) + one delete (GRN)
    assert db.get(AcEntityConfig, supplier.id).source_impl == SOURCE_IMPL_SQL_DB
    assert db.query(AcEntityConfig).filter(AcEntityConfig.id == grn_id).count() == 0
    assert _mapping_rows(db, DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE) == 0
    assert _source_impls(db, company.id) == {ENTITY_SUPPLIER: SOURCE_IMPL_SQL_DB}

    assert db.get(AcEntityConfig, ran_grn.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
    assert _mapping_rows(db, DEFAULT_TENANT_ID, ran_company.id, ENTITY_GOODS_RECEIVED_NOTE) == 2
    assert db.get(AcEntityConfig, api_grn.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
    assert _mapping_rows(db, DEFAULT_TENANT_ID, api_company.id, ENTITY_GOODS_RECEIVED_NOTE) == 2

    assert backfill_db_company_entity_sources(db, schema=None) == 0

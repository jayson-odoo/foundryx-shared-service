"""A DATABASE company's entity configs must be born (and repaired) as ``sql_db``.

Prod, 2026-09-06: a company whose source connection is a ``sql_database``
connection (``source_kind() == 'db'``) ended up with Customer/Supplier/GRN
entity configs at ``source_impl="autocount_read"`` because
``CompanyService.seed_company_defaults`` hardcodes that value - and the
entities list hides "Change source" on a DB company, so the operator had no
way out.

(1) ``seed_company_defaults`` seeds ``SOURCE_IMPL_SQL_DB`` on a DB company
    (an API company still gets ``autocount_read`` - control).
(2) ``backfill_db_company_entity_sources`` repairs existing rows: every
    ``autocount_read`` config on a DB company that has NEVER RUN flips to
    ``sql_db``; a config that has run is left alone; idempotent; tolerant of
    a bind with none of the tables; wired into ``update_tenant``.
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


def _mark_as_run(db, config: AcEntityConfig) -> None:
    """Every marker the pipeline leaves behind once an entity has synced: a
    watermark row with a high-water mark, and the config's own last run."""
    now = datetime.now(timezone.utc)
    db.add(
        AcWatermark(
            tenant_id=config.tenant_id, company_id=config.company_id,
            entity_type=config.entity_type, last_modified_at=now,
            last_success_at=now, last_attempt_at=now,
        )
    )
    config.last_run_at = now
    db.commit()


def _source_impls(db, company_id: str) -> dict:
    rows = (
        db.query(AcEntityConfig)
        .filter(AcEntityConfig.tenant_id == DEFAULT_TENANT_ID, AcEntityConfig.company_id == company_id)
        .all()
    )
    return {r.entity_type: r.source_impl for r in rows}


# ── (1) the seed follows the company's source kind ─────────────────────────


def test_seed_company_defaults_births_sql_db_configs_on_a_database_company(db):
    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")

    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    impls = _source_impls(db, company.id)
    assert set(impls) == set(SEEDED_ENTITIES)
    assert impls == {entity: SOURCE_IMPL_SQL_DB for entity in SEEDED_ENTITIES}


def test_seed_company_defaults_keeps_autocount_read_on_an_api_company(db):
    """Control: the vendor-API company is exactly as plan 13 births it."""
    company = _company(db, _api_connection(db, database="AED_API"), database="AED_API")

    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    impls = _source_impls(db, company.id)
    assert set(impls) == set(SEEDED_ENTITIES)
    assert impls == {entity: SOURCE_IMPL_AUTOCOUNT_READ for entity in SEEDED_ENTITIES}


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

    assert touched == len(SEEDED_ENTITIES)
    assert _source_impls(db, db_company.id) == {e: SOURCE_IMPL_SQL_DB for e in SEEDED_ENTITIES}
    assert _source_impls(db, api_company.id) == {
        e: SOURCE_IMPL_AUTOCOUNT_READ for e in SEEDED_ENTITIES
    }

    # Idempotent: nothing left to repair.
    assert backfill_db_company_entity_sources(db, schema=None) == 0


def test_backfill_leaves_a_config_that_has_already_run_untouched(db):
    """A row that has synced under ``autocount_read`` carries state that
    belongs to that source; flipping it silently would be a different bug.
    Only the never-run rows (the prod shape) are repaired."""
    from modules.autocount.backfill import backfill_db_company_entity_sources

    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    ran = _config(db, company, ENTITY_SUPPLIER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _mark_as_run(db, ran)
    fresh = _config(db, company, ENTITY_CUSTOMER, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    already = _config(db, company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_SQL_DB)

    touched = backfill_db_company_entity_sources(db, schema=None)
    db.commit()
    db.expire_all()

    assert touched == 1
    assert db.get(AcEntityConfig, ran.id).source_impl == SOURCE_IMPL_AUTOCOUNT_READ
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


def test_update_tenant_repairs_and_seeds_a_database_company_as_sql_db(db):
    """The composed path an existing host actually runs on a version bump:
    the stranded ``autocount_read`` row is repaired AND whatever the seed adds
    to the DB company is born ``sql_db`` - read back before any commit."""
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, _sql_connection(db, database="AED_DB"), database="AED_DB")
    stranded = _config(db, company, ENTITY_GOODS_RECEIVED_NOTE, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    stranded_id = stranded.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.5.0")

    impls = _source_impls(db, company.id)
    assert set(impls) == set(SEEDED_ENTITIES)
    assert db.get(AcEntityConfig, stranded_id).source_impl == SOURCE_IMPL_SQL_DB
    assert impls == {entity: SOURCE_IMPL_SQL_DB for entity in SEEDED_ENTITIES}

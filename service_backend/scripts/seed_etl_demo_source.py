"""DEV-ONLY: source tables for the direct-DB ETL demo (plan 22 S2/S3/S4/E2E).

    python -m scripts.seed_etl_demo_source                            # create + fill every table (idempotent)
    python -m scripts.seed_etl_demo_source --touch 3                  # bump customers row 3's watermark
    python -m scripts.seed_etl_demo_source --touch 3 --table products # bump products row 3's watermark
    python -m scripts.seed_etl_demo_source --delete-row 5             # remove customers row 5 (plan 22 S3)
    python -m scripts.seed_etl_demo_source --company                  # create/find the dedicated demo AcCompany

``--company`` (plan 22 S4 review B1.e) creates - or finds, idempotently - a
DEDICATED ``ac_company`` row for this demo rig: ``database_name='ETL_DEMO'``,
``sink_impl='logging'`` (never a real consumer). **Use this for every future
live-verify of the DB-ETL path** - a prior session instead reused the REAL
"V Soft Trading" company (a genuine Sorento-bound, ERP-discovered company from
plan 13/14) for DB-ETL live-verify, and a since-fixed live-verify DB mutation
on ITS ``database_name`` briefly poisoned its ref namespace (every master's
``source_ref`` is qualified by ``database_name``, AC-14-10 - see plan 22 S4
review B1). ``ETL_DEMO`` has its own namespace and its own sink ("logging" -
delivers nothing anywhere), so nothing a demo run does here can ever touch a
real company's Sorento state again. After creating it, configure entities the
normal way (Entities tab -> Add entity -> SQL Database source, pointed at this
same Postgres / ``public.etl_demo_<table>``) - this script only ensures the
company ROW exists; it does not seed entity configs (masters fan-out entities
are added on demand via the "Add entity" affordance, plan 22 S4 AC-22-23).

Creates ``public.etl_demo_<entity>`` tables **inside the Foundryx database
itself**, so a `sql_database` connection pointed back at `foundryx_service`
gives a real multi-row source with a real watermark column - no second
server, no customer data, no Docker. The task under test reads each table
exactly as it would read the matching AutoCount table.

    !!  THESE ARE DEV FIXTURES, NOT PRODUCT TABLES.  !!

They live in ``public`` (not ``app_autocount``) precisely so nothing mistakes
them for module data, none is created by a migration or by
``bootstrap_modules``, and no application code reads them - only a task an
operator configures by hand. Drop one with
``DROP TABLE public.etl_demo_<entity>`` whenever you like.

Plan 22 S4 (AC-22-23) added ``etl_demo_categories``/``etl_demo_uoms``/
``etl_demo_warehouses``/``etl_demo_products``/``etl_demo_agents`` - the
masters fan-out demo rig. ``etl_demo_products`` carries ``category_code``/
``uom_code`` referencing the categories/UOM tables' own codes (Sorento
resolves a product's category/UOM by CODE, not by ESB integration ref - see
``canonical/masters.py``'s ``CanonicalProduct`` docstring) - seeded so a
products task activated BEFORE the categories/UOM tasks demonstrates the
retryable -> next-run-resolves flow end to end.

``--touch N`` mutates row N's name/description and stamps ``last_modified``,
which is how the incremental leg is exercised: the next run must fetch
exactly that one row.

``--delete-row N`` (plan 22 S3) hard-deletes row N from the source table - the
next RECONCILE run must report it as a delete intent (there is no UI
affordance yet to force reconcile mode; drive it via a direct job enqueue, see
the plan's S3 live-verify notes).

``--table`` picks which demo table `--touch`/`--delete-row` act on (default
``customers``, unchanged from S2/S3 - existing invocations keep working).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal, engine
from app.models.tenant import Tenant
from app.secrets import encrypt_secret

DEMO_COMPANY_DATABASE_NAME = "ETL_DEMO"


@dataclass(frozen=True)
class DemoTable:
    """One demo source table: its name, DDL, primary key column (for
    ``--touch``/``--delete-row``), the "touch" column mutated to exercise the
    incremental leg, and its seed rows (column order matches ``columns``)."""

    key: str  # the --table value
    table: str
    ddl: str
    columns: Tuple[str, ...]
    pk: str
    touch_column: str
    rows: Sequence[Tuple[Any, ...]]


TABLES: Dict[str, DemoTable] = {
    "customers": DemoTable(
        key="customers",
        table="etl_demo_customers",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_customers (
                acc_no        text PRIMARY KEY,
                company_name  text NOT NULL,
                phone         text,
                email         text,
                is_active     boolean NOT NULL DEFAULT true,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("acc_no", "company_name", "phone", "email", "is_active"),
        pk="acc_no",
        touch_column="company_name",
        rows=[
            ("300-C001", "Aurora Trading Sdn Bhd", "+60123456701", "aurora@example.com", True),
            ("300-C002", "Bright Metals Sdn Bhd", "+60123456702", "bright@example.com", True),
            ("300-C003", "Cascade Logistics", "+60123456703", "cascade@example.com", True),
            ("300-C004", "Delta Hardware", "+60123456704", "delta@example.com", True),
            ("300-C005", "Everest Supplies", "+60123456705", "everest@example.com", True),
            ("300-C006", "Fairview Electricals", "+60123456706", "fairview@example.com", True),
            ("300-C007", "Granite Works", "+60123456707", "granite@example.com", False),
            ("300-C008", "Harbour Foods", "+60123456708", "harbour@example.com", True),
            ("300-C009", "Ironwood Timber", "+60123456709", "ironwood@example.com", True),
            ("300-C010", "Juniper Retail", "+60123456710", "juniper@example.com", True),
        ],
    ),
    # ── plan 22 S4 masters fan-out (AC-22-23) ─────────────────────────────────
    "categories": DemoTable(
        key="categories",
        table="etl_demo_categories",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_categories (
                category_code text PRIMARY KEY,
                category_name text NOT NULL,
                description   text,
                is_active     boolean NOT NULL DEFAULT true,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("category_code", "category_name", "description", "is_active"),
        pk="category_code",
        touch_column="category_name",
        rows=[
            ("CAT-BEV", "Beverages", "Drinks and mixers", True),
            ("CAT-HW", "Hardware", "Tools and fixings", True),
            ("CAT-ELEC", "Electricals", "Wiring and fittings", True),
            ("CAT-FOOD", "Food", "Packaged food", True),
            ("CAT-TMB", "Timber", "Cut and raw timber", True),
        ],
    ),
    "uoms": DemoTable(
        key="uoms",
        table="etl_demo_uoms",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_uoms (
                uom_code       text PRIMARY KEY,
                uom_name       text NOT NULL,
                decimal_places integer NOT NULL DEFAULT 0,
                description    text,
                is_active      boolean NOT NULL DEFAULT true,
                last_modified  timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("uom_code", "uom_name", "decimal_places", "description", "is_active"),
        pk="uom_code",
        touch_column="uom_name",
        rows=[
            ("PCS", "Pieces", 0, None, True),
            ("KG", "Kilogram", 2, None, True),
            ("BOX", "Box", 0, None, True),
            ("LTR", "Litre", 2, None, True),
            ("MTR", "Metre", 2, None, True),
        ],
    ),
    "warehouses": DemoTable(
        key="warehouses",
        table="etl_demo_warehouses",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_warehouses (
                warehouse_code text PRIMARY KEY,
                warehouse_name text NOT NULL,
                location       text,
                is_active      boolean NOT NULL DEFAULT true,
                last_modified  timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("warehouse_code", "warehouse_name", "location", "is_active"),
        pk="warehouse_code",
        touch_column="warehouse_name",
        rows=[
            ("WH-KL", "Kuala Lumpur main store", "Kuala Lumpur", True),
            ("WH-JB", "Johor Bahru branch", "Johor Bahru", True),
            ("WH-PEN", "Penang branch", "Penang", True),
            ("WH-KCH", "Kuching branch", "Kuching", True),
            ("WH-RTN", "Returns store", "Kuala Lumpur", False),
        ],
    ),
    "products": DemoTable(
        key="products",
        table="etl_demo_products",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_products (
                item_code     text PRIMARY KEY,
                description   text NOT NULL,
                category_code text,
                uom_code      text,
                price         numeric(12,2),
                is_active     boolean NOT NULL DEFAULT true,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("item_code", "description", "category_code", "uom_code", "price", "is_active"),
        pk="item_code",
        touch_column="description",
        rows=[
            # category_code/uom_code point at rows in etl_demo_categories/
            # etl_demo_uoms above - the retryable/carry-over demo (AC-22-23)
            # activates THIS task first, THEN those, on purpose.
            ("ITEM-001", "Mineral water 500ml", "CAT-BEV", "PCS", "1.50", True),
            ("ITEM-002", "Steel hex bolt M8", "CAT-HW", "PCS", "0.35", True),
            ("ITEM-003", "LED bulb 9W", "CAT-ELEC", "PCS", "6.90", True),
            ("ITEM-004", "Canned sardines 425g", "CAT-FOOD", "PCS", "3.20", True),
            ("ITEM-005", "Pine plank 2440mm", "CAT-TMB", "PCS", "18.00", True),
        ],
    ),
    "agents": DemoTable(
        key="agents",
        table="etl_demo_agents",
        ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_agents (
                agent_code    text PRIMARY KEY,
                agent_name    text,
                is_active     boolean NOT NULL DEFAULT true,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        columns=("agent_code", "agent_name", "is_active"),
        pk="agent_code",
        touch_column="agent_name",
        rows=[
            ("SEAN I", "Sean Ibrahim", True),
            ("LCL", "Lee Chin Loong", True),
            ("TAN R", "Tan Rui", True),
            ("SA04", "Nurul Aini", True),
            ("SA05", "David Wong", False),
        ],
    ),
}


# ── plan 22 S5 documents (AC-22-24) - header + line demo rig ─────────────────
#
# Two tables per document type (headers don't fit the flat single-table
# `DemoTable` shape above - a document task's line query is a SECOND query,
# never joined into the header). `last_modified` on the HEADER is the
# watermark; AutoCount's real behaviour (documented at
# `sql_source.source.SqlDbSource` construction) is that it stamps a header's
# `LastModified` whenever ANY of its lines change - `touch_document_line`
# below simulates this explicitly by touching BOTH the line and the header,
# never the line alone, so a live-verify run proves the S5 line-change-
# detection design rather than accidentally relying on watermark drift.


@dataclass(frozen=True)
class DemoDocument:
    key: str  # the --doc-table value
    header_table: str
    line_table: str
    header_ddl: str
    line_ddl: str
    header_columns: Tuple[str, ...]
    line_columns: Tuple[str, ...]
    header_rows: Sequence[Tuple[Any, ...]]  # doc_key first
    # doc_key -> [(dtl_key, ...line cols...), ...]
    lines_by_doc: Dict[str, Sequence[Tuple[Any, ...]]]


DOCUMENTS: Dict[str, DemoDocument] = {
    "sales_orders": DemoDocument(
        key="sales_orders",
        header_table="etl_demo_so_headers",
        line_table="etl_demo_so_lines",
        header_ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_so_headers (
                doc_key       text PRIMARY KEY,
                doc_no        text NOT NULL,
                debtor_code   text,
                agent_code    text,
                doc_date      date NOT NULL,
                cancelled     boolean NOT NULL DEFAULT false,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        line_ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_so_lines (
                dtl_key    text PRIMARY KEY,
                doc_key    text NOT NULL REFERENCES public.etl_demo_so_headers(doc_key),
                item_code  text NOT NULL,
                qty        numeric(12,4) NOT NULL,
                unit_price numeric(12,4),
                location   text
            )
        """,
        header_columns=("doc_key", "doc_no", "debtor_code", "agent_code", "doc_date", "cancelled"),
        line_columns=("dtl_key", "doc_key", "item_code", "qty", "unit_price", "location"),
        header_rows=[
            ("SO-D001", "SO-2601", "300-C001", "SEAN I", "2026-08-01", False),
            ("SO-D002", "SO-2602", "300-C002", "LCL", "2026-08-05", False),
            ("SO-D003", "SO-2603", "300-C003", "SEAN I", "2026-08-10", False),
        ],
        lines_by_doc={
            "SO-D001": [
                ("SO-D001-1", "SO-D001", "ITEM-001", "24", "1.50", "WH-KL"),
                ("SO-D001-2", "SO-D001", "ITEM-002", "100", "0.35", "WH-KL"),
            ],
            "SO-D002": [
                ("SO-D002-1", "SO-D002", "ITEM-003", "10", "6.90", "WH-JB"),
                ("SO-D002-2", "SO-D002", "ITEM-004", "48", "3.20", "WH-JB"),
                ("SO-D002-3", "SO-D002", "ITEM-005", "6", "18.00", "WH-JB"),
            ],
            "SO-D003": [
                ("SO-D003-1", "SO-D003", "ITEM-001", "12", "1.50", "WH-PEN"),
                ("SO-D003-2", "SO-D003", "ITEM-002", "50", "0.35", "WH-PEN"),
            ],
        },
    ),
    "purchase_orders": DemoDocument(
        key="purchase_orders",
        header_table="etl_demo_po_headers",
        line_table="etl_demo_po_lines",
        header_ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_po_headers (
                doc_key       text PRIMARY KEY,
                doc_no        text NOT NULL,
                creditor_code text,
                doc_date      date NOT NULL,
                cancelled     boolean NOT NULL DEFAULT false,
                last_modified timestamptz NOT NULL DEFAULT now()
            )
        """,
        line_ddl="""
            CREATE TABLE IF NOT EXISTS public.etl_demo_po_lines (
                dtl_key    text PRIMARY KEY,
                doc_key    text NOT NULL REFERENCES public.etl_demo_po_headers(doc_key),
                item_code  text NOT NULL,
                qty        numeric(12,4) NOT NULL,
                unit_price numeric(12,4),
                location   text
            )
        """,
        header_columns=("doc_key", "doc_no", "creditor_code", "doc_date", "cancelled"),
        line_columns=("dtl_key", "doc_key", "item_code", "qty", "unit_price", "location"),
        header_rows=[
            ("PO-D001", "PO-2601", "300-S001", "2026-08-02", False),
            ("PO-D002", "PO-2602", "300-S002", "2026-08-06", False),
            ("PO-D003", "PO-2603", "300-S001", "2026-08-11", False),
        ],
        lines_by_doc={
            "PO-D001": [
                ("PO-D001-1", "PO-D001", "ITEM-001", "200", "1.10", "WH-KL"),
                ("PO-D001-2", "PO-D001", "ITEM-002", "500", "0.22", "WH-KL"),
            ],
            "PO-D002": [
                ("PO-D002-1", "PO-D002", "ITEM-003", "80", "5.10", "WH-JB"),
            ],
            "PO-D003": [
                ("PO-D003-1", "PO-D003", "ITEM-004", "150", "2.40", "WH-PEN"),
                ("PO-D003-2", "PO-D003", "ITEM-005", "40", "13.50", "WH-PEN"),
            ],
        },
    ),
}


def seed_documents() -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    with engine.begin() as conn:
        for spec in DOCUMENTS.values():
            conn.execute(text(spec.header_ddl))
            conn.execute(text(spec.line_ddl))
            base = datetime.now(timezone.utc) - timedelta(days=len(spec.header_rows))
            hcols = ", ".join(spec.header_columns)
            hplaceholders = ", ".join(f":{c}" for c in spec.header_columns)
            for index, values in enumerate(spec.header_rows):
                params: Dict[str, Any] = dict(zip(spec.header_columns, values))
                params["stamp"] = base + timedelta(days=index)
                conn.execute(
                    text(
                        f"INSERT INTO public.{spec.header_table} "
                        f"({hcols}, last_modified) VALUES ({hplaceholders}, :stamp) "
                        f"ON CONFLICT (doc_key) DO NOTHING"
                    ),
                    params,
                )
            lcols = ", ".join(spec.line_columns)
            lplaceholders = ", ".join(f":{c}" for c in spec.line_columns)
            for lines in spec.lines_by_doc.values():
                for values in lines:
                    conn.execute(
                        text(
                            f"INSERT INTO public.{spec.line_table} ({lcols}) "
                            f"VALUES ({lplaceholders}) ON CONFLICT (dtl_key) DO NOTHING"
                        ),
                        dict(zip(spec.line_columns, values)),
                    )
            counts[spec.key] = {
                "headers": conn.execute(
                    text(f"SELECT count(*) FROM public.{spec.header_table}")
                ).scalar_one(),
                "lines": conn.execute(
                    text(f"SELECT count(*) FROM public.{spec.line_table}")
                ).scalar_one(),
            }
    return counts


def touch_document_line(doc_table: str, doc_key: str, *, qty_delta: str = "1") -> None:
    """Mutate ONE line's qty AND touch its header's ``last_modified`` -
    simulating AutoCount's real behaviour (a header's LastModified updates on
    ANY line edit, which is why the S5 design detects a line-only change by
    watching the HEADER watermark, never a per-line one)."""
    spec = DOCUMENTS[doc_table]
    with engine.begin() as conn:
        line_pk = conn.execute(
            text(f"SELECT dtl_key FROM public.{spec.line_table} WHERE doc_key = :dk LIMIT 1"),
            {"dk": doc_key},
        ).scalar_one_or_none()
        if line_pk is None:
            raise SystemExit(f"No line found for {doc_key} in {spec.line_table}.")
        conn.execute(
            text(
                f"UPDATE public.{spec.line_table} SET qty = qty + :delta "
                f"WHERE dtl_key = :pk"
            ),
            {"delta": qty_delta, "pk": line_pk},
        )
        conn.execute(
            text(
                f"UPDATE public.{spec.header_table} SET last_modified = now() "
                f"WHERE doc_key = :dk"
            ),
            {"dk": doc_key},
        )
    print(
        f"public.{spec.line_table}: bumped {line_pk}'s qty by {qty_delta} and "
        f"touched public.{spec.header_table} '{doc_key}'.last_modified."
    )


def cancel_document(doc_table: str, doc_key: str) -> None:
    """Cancel-at-source (Appendix A6 item 4) - the header's ``cancelled`` flag
    flips and its watermark advances, so the NEXT run re-pushes it as a
    STATUS UPDATE (never a delete - documents are never deleted by reconcile,
    plan 22 S5)."""
    spec = DOCUMENTS[doc_table]
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE public.{spec.header_table} SET cancelled = true, "
                f"last_modified = now() WHERE doc_key = :dk"
            ),
            {"dk": doc_key},
        )
    print(f"public.{spec.header_table}: '{doc_key}' marked cancelled + watermark touched.")


def _guard() -> None:
    """Refuse to run outside development. A demo table is harmless, but a
    script that plants rows in a production database on a typo is not."""
    if settings.environment != "development":
        raise SystemExit(
            f"Refusing to seed the ETL demo source in '{settings.environment}'. "
            "This is a development fixture."
        )


def seed() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    with engine.begin() as conn:
        for spec in TABLES.values():
            conn.execute(text(spec.ddl))
            base = datetime.now(timezone.utc) - timedelta(days=len(spec.rows))
            col_list = ", ".join(spec.columns)
            placeholders = ", ".join(f":{c}" for c in spec.columns)
            for index, values in enumerate(spec.rows):
                params: Dict[str, Any] = dict(zip(spec.columns, values))
                params["stamp"] = base + timedelta(days=index)
                conn.execute(
                    text(
                        f"INSERT INTO public.{spec.table} "
                        f"({col_list}, last_modified) VALUES ({placeholders}, :stamp) "
                        # Idempotent: re-running must NOT bump every watermark, or
                        # the next incremental run would re-fetch the whole table.
                        f"ON CONFLICT ({spec.pk}) DO NOTHING"
                    ),
                    params,
                )
            counts[spec.key] = conn.execute(
                text(f"SELECT count(*) FROM public.{spec.table}")
            ).scalar_one()
    return counts


def touch(table_key: str, row: int) -> str:
    """Mutate ONE row and stamp it now - the incremental leg's trigger."""
    spec = TABLES[table_key]
    pk_value = spec.rows[(row - 1) % len(spec.rows)][0]
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE public.{spec.table} SET "
                f"{spec.touch_column} = {spec.touch_column} || ' (updated)', "
                f"last_modified = now() WHERE {spec.pk} = :pk"
            ),
            {"pk": pk_value},
        )
    return str(pk_value)


def delete_row(table_key: str, row: int) -> str:
    """Hard-delete ONE row - the reconcile leg's trigger (plan 22 S3,
    AC-22-16/32): a later reconcile finds this ref previously known but
    absent from the extract and stages a delete intent."""
    spec = TABLES[table_key]
    pk_value = spec.rows[(row - 1) % len(spec.rows)][0]
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM public.{spec.table} WHERE {spec.pk} = :pk"),
            {"pk": pk_value},
        )
    return str(pk_value)


def ensure_demo_company(tenant_slug: str = "default") -> str:
    """Create - or find, idempotently - the dedicated demo company (label
    "ETL Demo Co").

    Deliberately built with plain ORM writes rather than the real onboarding
    ceremony (``CompanyService.create_from_connection``): that path SIGNS IN
    to a real AutoCount API to DISCOVER ``database_name`` (AC-13-01, "a
    company is discovered, never typed") - there is no AutoCount server for
    this dev-only DB-ETL rig to sign in to. This is fixture code, the same
    spirit as the demo tables above, not a product code path.

    ``database_name`` MUST equal the real Postgres database a ``sql_db``
    task's connection reads (plan 22 S2 review SHOULD-FIX 6,
    ``EtlService.update_task``'s cross-check: "a connection pointed at a
    DIFFERENT database would extract someone else's data under this
    company's identity" - 422 ``connectionId`` otherwise) - discovered live
    via plan 22 S6's E2E, which is the first thing to ever drive this
    company through the REAL ``update_task`` service path (unit tests
    construct ``AcEntityConfig`` rows directly and never hit the check). A
    fixed label like ``ETL_DEMO`` would never match the real Postgres
    database this rig's own connection points at (this same process' own
    ``DATABASE_URL``), so a customer task pointed at that database could
    never save. ``DEMO_COMPANY_DATABASE_NAME`` stays the LOOKUP key (a
    dev-only Postgres database is never renamed mid-session); the company's
    row is migrated onto the real physical name on find, one ORM UPDATE, so
    a company created before this fix self-heals on the next
    ``--company`` run instead of leaving a permanently-broken demo fixture.

    Returns the company id. Import lazily (module-level import would pull the
    whole autocount package into every ``--touch``/``--delete-row`` run).
    """
    from modules.autocount.models import SINK_IMPL_LOGGING, AcCompany
    from modules.autocount.repositories import CompanyRepository
    from modules.autocount.sql_provider import (
        SQL_DATABASE_CONNECTION_TYPE,
        SQL_DATABASE_PROVIDER_KEY,
    )
    from app.models.connection import Connection

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug '{tenant_slug}'.")

        # The real physical Postgres database this process' own DATABASE_URL
        # names - the demo tables live in `public` on this very engine, so a
        # `sql_database` connection pointed at it is a REAL, working source
        # (never a second server, never customer data).
        url = make_url(settings.database_url)
        real_db_name = url.database or DEMO_COMPANY_DATABASE_NAME

        companies = CompanyRepository(db)
        existing = companies.get_by_database_name(tenant.id, real_db_name)
        if existing is None:
            # Legacy row from before this fix - same company, wrong
            # `database_name`. Migrate in place (its OWN connection's
            # `config.database` was ALWAYS the real name - only the company
            # row's label was stale) rather than leaving a dead duplicate.
            existing = companies.get_by_database_name(tenant.id, DEMO_COMPANY_DATABASE_NAME)
            if existing is not None:
                existing.database_name = real_db_name
                db.commit()
                db.refresh(existing)
                print(
                    f"Migrated company database_name '{DEMO_COMPANY_DATABASE_NAME}' -> "
                    f"'{real_db_name}' on {existing.id} (S2 review SHOULD-FIX 6)."
                )
        if existing is not None:
            print(f"Company '{real_db_name}' already exists: {existing.id} (sink={existing.sink_impl}).")
            return existing.id

        conn = Connection(
            tenant_id=tenant.id,
            provider=SQL_DATABASE_PROVIDER_KEY,
            type=SQL_DATABASE_CONNECTION_TYPE,
            name="ETL Demo Source (local Postgres)",
            config_json={
                "dbType": "postgresql",
                "host": url.host or "localhost",
                "port": url.port or 5432,
                "database": real_db_name,
                "username": url.username or "",
            },
            credentials_json=encrypt_secret({"password": url.password or ""}),
        )
        db.add(conn)
        db.flush()

        company = AcCompany(
            tenant_id=tenant.id,
            connection_id=conn.id,
            database_name=real_db_name,
            company_name="ETL Demo Co",
            name="ETL Demo Co",
            is_active=True,
            # Never a real consumer (plan 22 S4 review B1.e) - this company's
            # whole point is that nothing it does can reach Sorento.
            sink_impl=SINK_IMPL_LOGGING,
        )
        companies.add(company)
        db.flush()

        # Standard onboarding seeds the goods-received-note/supplier/customer
        # entity configs (source_impl='autocount_read') + their DEFAULT_MAPPINGS
        # - `create_from_connection` does this, but this rig deliberately
        # bypasses that ceremony (no real AutoCount to sign in to), so it is
        # replicated here directly (plan 22 S6 - E2E needs "Customer" reachable
        # via the SAME "Change source" flow the S2 live-verify used on a real
        # company, never a bespoke path). Seed-if-absent, so a re-run against an
        # already-provisioned company is a no-op.
        from modules.autocount.services.company_service import CompanyService

        CompanyService(db).seed_company_defaults(tenant.id, company.id)
        db.commit()
        print(
            f"Created company '{real_db_name}': {company.id} "
            f"(sink=logging, connection={conn.id}), with the standard "
            "goods_received_note/supplier/customer entity configs seeded.\n"
            "Next: AutoCount -> this company -> Entities tab -> Customer -> "
            "'...' -> Change source -> Database -> Configure database query, "
            "pointed at 'public.etl_demo_<table>' above."
        )
        return company.id
    finally:
        db.close()


def trigger_run(
    company_database_name: str,
    entity_type: str,
    mode: str,
    *,
    tenant_slug: str = "default",
) -> Dict[str, Any]:
    """Directly enqueue ONE ``autocount_sync`` job - the SAME
    ``JobService.create_and_enqueue`` call the backend's own "Run now" button
    makes, just with an explicit ``mode`` override.

    Plan 22 S3/S6: there is deliberately NO UI affordance to force a RECONCILE
    run (it is schedule- or beat-driven in production; "Run now" always enqueues
    ``manual``, which behaves as an incremental fetch whenever the task has a
    watermark column - see ``SqlDbSource.fetch_changes``'s ``full_extract``
    gate). E2E's change-detection journey (AC-22-32) needs a reconcile run on
    demand to prove delete-intent detection, so this is that "small backend
    helper" - it does not skip or shortcut anything the product itself does not
    already do; it only supplies the mode a human would otherwise wait for the
    scheduler to pick.

    Runs INLINE under ``CELERY_TASK_ALWAYS_EAGER=true`` (local dev/E2E), so this
    returns only once the run has actually finished.
    """
    from app.jobs.service import JobService
    from app.models.tenant import Tenant
    from modules.autocount.repositories import CompanyRepository

    # Import side effect: registers the `sql_db` source factory (see the
    # module-level comment above `register_sql_db_source()` in `sync.py`) - a
    # process that enqueues a `sql_db` run without this import fails loudly
    # with "no source implementation registered", not silently.
    from modules.autocount.sync import AUTOCOUNT_SYNC  # noqa: F401

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug '{tenant_slug}'.")
        company = CompanyRepository(db).get_by_database_name(tenant.id, company_database_name)
        if company is None:
            raise SystemExit(f"No company '{company_database_name}' for tenant '{tenant_slug}'.")

        job = JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC,
            tenant_id=tenant.id,
            payload={"companyId": company.id, "entityType": entity_type, "mode": mode},
        )
        db.commit()
        db.refresh(job)
        return {"jobId": job.id, "status": job.status, "error": job.error}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        choices=sorted(TABLES),
        default="customers",
        help="which demo table --touch/--delete-row act on (default: customers)",
    )
    parser.add_argument(
        "--touch",
        type=int,
        metavar="N",
        help="mutate row N (1-based) and stamp its watermark now",
    )
    parser.add_argument(
        "--delete-row",
        type=int,
        metavar="N",
        help="hard-delete row N (1-based) - the next reconcile stages a delete intent",
    )
    parser.add_argument(
        "--company",
        action="store_true",
        help=(
            "create/find the dedicated ETL_DEMO company (sink=logging) so "
            "live verifies never touch a real company's ref namespace"
        ),
    )
    parser.add_argument(
        "--tenant-slug",
        default="default",
        help="tenant slug for --company (default: 'default')",
    )
    parser.add_argument(
        "--doc-table",
        choices=sorted(DOCUMENTS),
        help="plan 22 S5 - which document (sales_orders|purchase_orders) --touch-line/--cancel-doc act on",
    )
    parser.add_argument(
        "--touch-line",
        metavar="DOC_KEY",
        help="plan 22 S5 - bump one line's qty + touch its header's watermark (simulates AutoCount)",
    )
    parser.add_argument(
        "--cancel-doc",
        metavar="DOC_KEY",
        help="plan 22 S5 - mark a header cancelled + touch its watermark (status update, never a delete)",
    )
    parser.add_argument(
        "--trigger-run",
        metavar="ENTITY_TYPE",
        help=(
            "plan 22 S6 - directly enqueue ONE autocount_sync job for this "
            "entity (e.g. 'customer'), bypassing the UI's 'Run now' (which "
            "always enqueues mode=manual). Pair with --run-mode."
        ),
    )
    parser.add_argument(
        "--run-mode",
        choices=("manual", "incremental", "reconcile"),
        default="reconcile",
        help="the mode --trigger-run enqueues (default: reconcile - the mode with no UI affordance)",
    )
    parser.add_argument(
        "--company-database",
        # The demo company's `database_name` is the REAL physical Postgres
        # database (see `ensure_demo_company`'s docstring) - this process' own
        # `DATABASE_URL` names it, so the default is derived, never the stale
        # `ETL_DEMO` label.
        default=make_url(settings.database_url).database or DEMO_COMPANY_DATABASE_NAME,
        help="which company's task --trigger-run targets (default: this process' own database - the demo company)",
    )
    args = parser.parse_args()
    _guard()

    if args.company:
        ensure_demo_company(args.tenant_slug)
        return
    if args.trigger_run:
        result = trigger_run(
            args.company_database, args.trigger_run, args.run_mode, tenant_slug=args.tenant_slug
        )
        print(f"triggered {args.run_mode} run for '{args.trigger_run}': {result}")
        return
    if args.touch_line:
        if not args.doc_table:
            raise SystemExit("--touch-line needs --doc-table sales_orders|purchase_orders.")
        touch_document_line(args.doc_table, args.touch_line)
        return
    if args.cancel_doc:
        if not args.doc_table:
            raise SystemExit("--cancel-doc needs --doc-table sales_orders|purchase_orders.")
        cancel_document(args.doc_table, args.cancel_doc)
        return
    if args.touch:
        pk_value = touch(args.table, args.touch)
        print(f"touched public.{TABLES[args.table].table} row {pk_value} - its watermark is now.")
        return
    if args.delete_row:
        pk_value = delete_row(args.table, args.delete_row)
        print(
            f"deleted public.{TABLES[args.table].table} row {pk_value} - the next "
            "RECONCILE run should stage it as a delete intent."
        )
        return
    counts = seed()
    for spec in TABLES.values():
        print(f"public.{spec.table}: {counts[spec.key]} row(s) ready.")
    doc_counts = seed_documents()
    for spec in DOCUMENTS.values():
        c = doc_counts[spec.key]
        print(f"public.{spec.header_table}: {c['headers']} row(s), public.{spec.line_table}: {c['lines']} row(s) ready.")
    print(
        "Point a `sql_database` connection at this database "
        "(postgresql / localhost / 5432 / foundryx_service) and query "
        "`SELECT * FROM public.etl_demo_<table>` - see each table's key/watermark above."
    )


if __name__ == "__main__":
    main()

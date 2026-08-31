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
    """Create - or find, idempotently - the dedicated ``ETL_DEMO`` company.

    Deliberately built with plain ORM writes rather than the real onboarding
    ceremony (``CompanyService.create_from_connection``): that path SIGNS IN
    to a real AutoCount API to DISCOVER ``database_name`` (AC-13-01, "a
    company is discovered, never typed") - there is no AutoCount server for
    this dev-only DB-ETL rig to sign in to. This is fixture code, the same
    spirit as the demo tables above, not a product code path.

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

        companies = CompanyRepository(db)
        existing = companies.get_by_database_name(tenant.id, DEMO_COMPANY_DATABASE_NAME)
        if existing is not None:
            print(
                f"Company '{DEMO_COMPANY_DATABASE_NAME}' already exists: {existing.id} "
                f"(sink={existing.sink_impl})."
            )
            return existing.id

        # A same-Postgres ``sql_database`` connection pointed at THIS database -
        # the demo tables above live in ``public`` on the very engine this
        # script already runs against, so the URL is derived, never re-typed.
        url = make_url(settings.database_url)
        conn = Connection(
            tenant_id=tenant.id,
            provider=SQL_DATABASE_PROVIDER_KEY,
            type=SQL_DATABASE_CONNECTION_TYPE,
            name="ETL Demo Source (local Postgres)",
            config_json={
                "dbType": "postgresql",
                "host": url.host or "localhost",
                "port": url.port or 5432,
                "database": url.database or "",
                "username": url.username or "",
            },
            credentials_json=encrypt_secret({"password": url.password or ""}),
        )
        db.add(conn)
        db.flush()

        company = AcCompany(
            tenant_id=tenant.id,
            connection_id=conn.id,
            database_name=DEMO_COMPANY_DATABASE_NAME,
            company_name="ETL Demo Co",
            name="ETL Demo Co",
            is_active=True,
            # Never a real consumer (plan 22 S4 review B1.e) - this company's
            # whole point is that nothing it does can reach Sorento.
            sink_impl=SINK_IMPL_LOGGING,
        )
        companies.add(company)
        db.commit()
        print(
            f"Created company '{DEMO_COMPANY_DATABASE_NAME}': {company.id} "
            f"(sink=logging, connection={conn.id}).\n"
            "Next: AutoCount -> this company -> Entities tab -> Add entity -> "
            "SQL Database source, pointed at 'public.etl_demo_<table>' above."
        )
        return company.id
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
    args = parser.parse_args()
    _guard()

    if args.company:
        ensure_demo_company(args.tenant_slug)
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
    print(
        "Point a `sql_database` connection at this database "
        "(postgresql / localhost / 5432 / foundryx_service) and query "
        "`SELECT * FROM public.etl_demo_<table>` - see each table's key/watermark above."
    )


if __name__ == "__main__":
    main()

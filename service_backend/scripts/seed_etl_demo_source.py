"""DEV-ONLY: a source table for the direct-DB ETL demo (plan 22 S2/E2E).

    python -m scripts.seed_etl_demo_source                 # create + fill (idempotent)
    python -m scripts.seed_etl_demo_source --touch 3        # bump 1 row's watermark
    python -m scripts.seed_etl_demo_source --delete-row 5   # remove 1 row (plan 22 S3)

Creates ``public.etl_demo_customers`` **inside the Foundryx database itself**,
so a `sql_database` connection pointed back at `foundryx_service` gives a real
multi-row source with a real watermark column - no second server, no customer
data, no Docker. The task under test reads it exactly as it would read a
customer's AutoCount database.

    !!  THIS IS A DEV FIXTURE, NOT A PRODUCT TABLE.  !!

It is in ``public`` (not ``app_autocount``) precisely so nothing mistakes it
for module data, it is never created by a migration or by ``bootstrap_modules``,
and no application code reads it - only a task an operator configures by hand.
Drop it with ``DROP TABLE public.etl_demo_customers`` whenever you like.

``--touch N`` mutates row N's ``company_name`` and stamps ``last_modified``,
which is how the incremental leg is exercised: the next run must fetch exactly
that one row.

``--delete-row N`` (plan 22 S3) hard-deletes row N from the source table - the
next RECONCILE run must report it as a delete intent (there is no UI
affordance yet to force reconcile mode; drive it via a direct job enqueue, see
the plan's S3 live-verify notes).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.database import engine

TABLE = "etl_demo_customers"

DDL = f"""
CREATE TABLE IF NOT EXISTS public.{TABLE} (
    acc_no        text PRIMARY KEY,
    company_name  text NOT NULL,
    phone         text,
    email         text,
    is_active     boolean NOT NULL DEFAULT true,
    last_modified timestamptz NOT NULL DEFAULT now()
)
"""

# Ten rows with STAGGERED watermarks, so an incremental fetch has something
# meaningful to be bounded by (all-identical stamps would make any WHERE
# clause look correct).
ROWS = [
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
]


def _guard() -> None:
    """Refuse to run outside development. A demo table is harmless, but a
    script that plants rows in a production database on a typo is not."""
    if settings.environment != "development":
        raise SystemExit(
            f"Refusing to seed the ETL demo source in '{settings.environment}'. "
            "This is a development fixture."
        )


def seed() -> int:
    base = datetime.now(timezone.utc) - timedelta(days=len(ROWS))
    with engine.begin() as conn:
        conn.execute(text(DDL))
        for index, (acc_no, name, phone, email, active) in enumerate(ROWS):
            conn.execute(
                text(
                    f"INSERT INTO public.{TABLE} "
                    "(acc_no, company_name, phone, email, is_active, last_modified) "
                    "VALUES (:acc_no, :name, :phone, :email, :active, :stamp) "
                    # Idempotent: re-running must NOT bump every watermark, or
                    # the next incremental run would re-fetch the whole table.
                    "ON CONFLICT (acc_no) DO NOTHING"
                ),
                {
                    "acc_no": acc_no,
                    "name": name,
                    "phone": phone,
                    "email": email,
                    "active": active,
                    "stamp": base + timedelta(days=index),
                },
            )
        return conn.execute(text(f"SELECT count(*) FROM public.{TABLE}")).scalar_one()


def touch(row: int) -> str:
    """Mutate ONE row and stamp it now - the incremental leg's trigger."""
    acc_no = ROWS[(row - 1) % len(ROWS)][0]
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE public.{TABLE} SET "
                "company_name = company_name || ' (updated)', "
                "last_modified = now() WHERE acc_no = :acc_no"
            ),
            {"acc_no": acc_no},
        )
    return acc_no


def delete_row(row: int) -> str:
    """Hard-delete ONE row - the reconcile leg's trigger (plan 22 S3,
    AC-22-16/32): a later reconcile finds this ref previously known but
    absent from the extract and stages a delete intent."""
    acc_no = ROWS[(row - 1) % len(ROWS)][0]
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM public.{TABLE} WHERE acc_no = :acc_no"),
            {"acc_no": acc_no},
        )
    return acc_no


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args()
    _guard()

    if args.touch:
        acc_no = touch(args.touch)
        print(f"touched public.{TABLE} row {acc_no} - its watermark is now.")
        return
    if args.delete_row:
        acc_no = delete_row(args.delete_row)
        print(
            f"deleted public.{TABLE} row {acc_no} - the next RECONCILE run "
            "should stage it as a delete intent."
        )
        return
    total = seed()
    print(f"public.{TABLE}: {total} row(s) ready.")
    print(
        "Point a `sql_database` connection at this database "
        "(postgresql / localhost / 5432 / foundryx_service) and query "
        f"`SELECT * FROM public.{TABLE}` - key `acc_no`, watermark `last_modified`."
    )


if __name__ == "__main__":
    main()

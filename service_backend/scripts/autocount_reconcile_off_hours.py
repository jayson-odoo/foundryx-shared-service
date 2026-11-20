"""SS-SO-FAST-QUEUE - owner-run: move AutoCount reconciles to 02:00-05:00 MYT.

Dry-run (default) prints every task's schedule before -> after and writes
nothing. Sales orders move to a 30-second incremental (``--so-seconds``),
other documents to 1 minute, reconciles to 02:00-05:00 MYT. ``--apply`` writes the same change set and re-arms ACTIVE tasks.
Idempotent: a second run proposes no change.

    docker compose exec worker_jobs python -m scripts.autocount_reconcile_off_hours
    docker compose exec worker_jobs python -m scripts.autocount_reconcile_off_hours --apply

Rollback: the dry-run output lists every old value (incrementalMinutes,
reconcileAt, reconcileTimezone - none = UTC); set them back in the task editor.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry-run)")
    parser.add_argument(
        "--so-seconds", type=int, default=30,
        help="sales_order incremental in seconds (default 30; 0 = leave SO on minutes)",
    )
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from modules.autocount.schedule_tuning import (
        apply_off_hours_schedule,
        plan_off_hours_schedule,
        render_plan,
    )

    if args.so_seconds and not 15 <= args.so_seconds <= 3600:
        parser.error("--so-seconds must be 15-3600, or 0 to leave sales orders on minutes")
    db = SessionLocal()
    try:
        plan = plan_off_hours_schedule(db, so_seconds=args.so_seconds or None)
        print(render_plan(plan))
        if not args.apply:
            print("\nDRY RUN - re-run with --apply to write.")
            return 0
        changed = apply_off_hours_schedule(db, plan)
        print(f"\nApplied: {changed} task(s) changed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

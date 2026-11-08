"""SS-SO-FAST-QUEUE - owner-run: move AutoCount reconciles to 02:00-05:00 MYT.

Dry-run (default) prints every task's schedule before -> after and writes
nothing. ``--apply`` writes the same change set and re-arms ACTIVE tasks.
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
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from modules.autocount.schedule_tuning import (
        apply_off_hours_schedule,
        plan_off_hours_schedule,
        render_plan,
    )

    db = SessionLocal()
    try:
        plan = plan_off_hours_schedule(db)
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

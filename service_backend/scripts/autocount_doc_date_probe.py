"""SLOW-MOVING-BACKFILL S0.1 - read-only: a book's earliest DO and GRN DocDate.

Reads only the vendor ``bydocdate`` doors of the company's configured doc
feeds (no writes anywhere, no CRM call). Prints one line per feed with the
earliest day found and the backfill floor it implies.

    docker compose exec worker_jobs python -m scripts.autocount_doc_date_probe --company <company id>
    ... --from 2010-01-01 --to 2019-01-07 --stride 7

Only point it at the book you mean to probe (dev: db3).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--company", required=True, help="AutoCount company id")
    parser.add_argument("--from", dest="from_day", default="2010-01-01", help="first day to probe")
    parser.add_argument("--to", dest="to_day", default=None, help="last day to probe (default: the floor + 6 days)")
    parser.add_argument("--stride", type=int, default=7, help="coarse pass step in days (default 7)")
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    import modules.autocount.services  # noqa: F401  (import order: avoids the runner/jobs cycle)
    from modules.autocount.doc_feed.constants import BACKFILL_FROM_DEFAULT, DOCUMENT_FEEDS
    from modules.autocount.doc_feed.probe import earliest_doc_day, floor_for
    from modules.autocount.doc_feed.runner import RunRefusal, resolve_vendor
    from modules.autocount.models import AcDocFeed

    default_floor = date.fromisoformat(BACKFILL_FROM_DEFAULT)
    from_day = date.fromisoformat(args.from_day)
    to_day = date.fromisoformat(args.to_day) if args.to_day else date.fromordinal(default_floor.toordinal() + 6)
    db = SessionLocal()
    try:
        rows = db.query(AcDocFeed).filter(AcDocFeed.company_id == args.company).all()
        by_feed = {row.feed: row for row in rows}
        for feed in DOCUMENT_FEEDS:
            row = by_feed.get(feed)
            if row is None:
                print(f"{feed}: not configured")
                continue
            try:
                resolved = resolve_vendor(db, row)
            except RunRefusal as exc:
                print(f"{feed}: {exc}")
                continue
            reads = {"n": 0}

            def read_day(day, _feed=feed, _vendor=resolved.vendor):
                reads["n"] += 1
                return _vendor.day_by_doc_date(_feed, day)

            earliest = earliest_doc_day(read_day, from_day=from_day, to_day=to_day, stride=args.stride)
            floor = floor_for(earliest, default_floor=default_floor)
            found = earliest.strftime("%d/%m/%Y") if earliest else "none in range"
            print(
                f"{feed} book={resolved.book}: earliest {found}; floor {floor.strftime('%d/%m/%Y')}"
                f" ({reads['n']} reads, {from_day.isoformat()}..{to_day.isoformat()})"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

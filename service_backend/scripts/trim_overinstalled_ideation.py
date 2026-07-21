"""One-off cleanup: trim the over-broad ideation install.

Context: ideation was force-installed (dependency check bypassed) for all ~25
tenants during local integration testing. Ideation ``requires:["omnichannel"]``
and omnichannel is only installed for the demo tenant, so the correct keep-set
is exactly the tenant(s) that have omnichannel. The 24 extra tenants have ZERO
ideas (verified 2026-07-19) — trimming their ``tenant_modules`` rows orphans
nothing and is reversible from the snapshot this script writes.

Run (dry-run by default, prints what it would do):
    .venv/bin/python scripts/trim_overinstalled_ideation.py

Apply:
    .venv/bin/python scripts/trim_overinstalled_ideation.py --apply

Restore from snapshot:
    .venv/bin/python scripts/trim_overinstalled_ideation.py --restore <snapshot.json>
"""
import argparse
import datetime as _dt
import json
import sys

from sqlalchemy import create_engine, text


def _db_url() -> str:
    for line in open(".env"):
        if line.startswith("DATABASE_URL="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("DATABASE_URL not found in .env")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the delete (default: dry-run)")
    ap.add_argument("--restore", metavar="SNAPSHOT", help="re-insert rows from a snapshot json")
    ap.add_argument("--snapshot", default="ideation_tenant_modules_snapshot.json")
    args = ap.parse_args()

    eng = create_engine(_db_url())

    # Resolve ideation module id + the keep-set (tenants that have omnichannel).
    with eng.connect() as c:
        ide = c.execute(text("SELECT id FROM modules WHERE name='ideation'")).scalar()
        omni = c.execute(text("SELECT id FROM modules WHERE name='omnichannel'")).scalar()
        if ide is None or omni is None:
            raise SystemExit("ideation/omnichannel module rows not found")
        keep = [str(r[0]) for r in c.execute(
            text("SELECT tenant_id FROM tenant_modules WHERE module_id=:m"), {"m": omni})]

    if args.restore:
        rows = json.load(open(args.restore))
        with eng.begin() as c:
            for r in rows:
                c.execute(text(
                    "INSERT INTO tenant_modules (id, tenant_id, module_id, status, installed_version, installed_at, updated_at) "
                    "VALUES (:id,:tenant_id,:module_id,:status,:installed_version,:installed_at,:updated_at) "
                    "ON CONFLICT (id) DO NOTHING"), r)
        print(f"restored {len(rows)} rows from {args.restore}")
        return 0

    with eng.connect() as c:
        victims = [dict(r._mapping) for r in c.execute(text(
            "SELECT * FROM tenant_modules WHERE module_id=:m AND tenant_id <> ALL(:keep)"),
            {"m": ide, "keep": keep})]

    print(f"ideation module: {ide}")
    print(f"keep tenants (have omnichannel): {keep}")
    print(f"rows to trim: {len(victims)}")
    for v in victims:
        print("  -", v["tenant_id"])

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to delete.")
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 (local one-off)
    snap = args.snapshot.replace(".json", f".{stamp}.json")
    json.dump(victims, open(snap, "w"), default=str, indent=2)
    print(f"snapshot written: {snap}")

    with eng.begin() as c:
        res = c.execute(text(
            "DELETE FROM tenant_modules WHERE module_id=:m AND tenant_id <> ALL(:keep)"),
            {"m": ide, "keep": keep})
        print(f"deleted {res.rowcount} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())

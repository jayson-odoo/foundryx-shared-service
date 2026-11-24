"""Operator CLI for write-back setup (plan 55 hardening, H12).

    python -m modules.autocount.write_back.admin set-write-connection \\
        --tenant-slug <slug> --company-id <uuid> --connection-id <uuid>
    python -m modules.autocount.write_back.admin set-line-notes-connection \\
        --tenant-slug <slug> --company-id <uuid> [--connection-id <uuid>]   (omit = clear)
    python -m modules.autocount.write_back.admin check-line-notes   (release guard: exit 1 only when a set line notes
        database fails its read-only probe; a company with none is printed NO_CONNECTION, exit 0)

Prints a result code only, never a URL.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from modules.autocount.services.company_service import AutocountServiceError, CompanyService
from modules.autocount.write_back.line_notes_check import READ_FAILED, check_line_notes
from modules.autocount.write_back.service import WriteConnectionError, set_write_connection


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write-back administration.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("set-write-connection")
    cmd.add_argument("--tenant-slug", required=True)
    cmd.add_argument("--company-id", required=True)
    cmd.add_argument("--connection-id", required=True)
    notes = sub.add_parser("set-line-notes-connection")
    notes.add_argument("--tenant-slug", required=True)
    notes.add_argument("--company-id", required=True)
    notes.add_argument("--connection-id", default=None)
    sub.add_parser("check-line-notes")
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from app.models.tenant import Tenant

    if args.command == "check-line-notes":
        with SessionLocal() as db:
            results = check_line_notes(db)
        for company_id, code in results:
            print(f"{company_id} {code}")
        return 1 if any(code == READ_FAILED for _id, code in results) else 0  # NO_CONNECTION is a warning only

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print("error: unknown tenant")
            return 2
        try:
            if args.command == "set-line-notes-connection":
                CompanyService(db).set_line_notes_connection(tenant.id, args.company_id, args.connection_id)
            else:
                set_write_connection(
                    db, tenant_id=tenant.id, company_id=args.company_id,
                    connection_id=args.connection_id,
                )
        except WriteConnectionError as exc:
            print(f"error: {exc.code}")
            return 2
        except AutocountServiceError:
            print("error: CONNECTION_NOT_FOUND")
            return 2
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

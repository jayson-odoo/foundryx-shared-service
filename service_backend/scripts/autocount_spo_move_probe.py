"""Plan 71 db3 probe: split, then whole-move back, one SPO line through the REAL ``spo_move_row``.

Writes ONLY to the db3 test book: the script refuses unless the company's write connection names
``db3`` (a test book) and the company passes the test-company guard. The ``spo_move`` switch is
turned on for THIS process only (the deployed default stays off). Every vendor call goes through
the normal write frame, so each one is in ``ac_api_call_log`` under the operation id.

Needs an SPO made in AutoCount on db3 (F14: the API cannot create one) with a line tied to a PO
row (PO-A), plus a PO-B row of the same item and unit with room for the take.

    # 1. look first (no write): prints the SPO lines
    docker compose exec worker_jobs python -m scripts.autocount_spo_move_probe --company <id> \\
        --spo <spoDocKey> --look
    # 2. probe: split <line> by --qty onto PO-B, read back, move the new line whole back to PO-A, read back
    docker compose exec worker_jobs python -m scripts.autocount_spo_move_probe --company <id> \\
        --spo <spoDocKey> --line <spoDtlKey> --from-po <poADocKey> --to-po <poBDocKey> \\
        --to-line <poBDtlKey> --qty <n>

Output is masked: keys, quantities, item codes, link keys, outcomes and the logged calls (method,
path without host, status). No price, party, host or credential is printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Dict, List, Optional

TEST_BOOK = "db3"


def _lines(doc: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in (doc or {}).get("Details") or []:
        out.append({
            "dtlKey": r.get("DtlKey"), "item": r.get("ItemCode"), "uom": r.get("UOM"),
            "qty": str(r.get("Qty")), "fromDocType": r.get("FromDocType") or "",
            "fromDocNo": r.get("FromDocNo") or "", "fromDocDtlKey": r.get("FromDocDtlKey") or 0,
            "received": None if r.get("TransferedQty") is None else str(r.get("TransferedQty")),
        })
    return out


def _print(title: str, value: Any) -> None:
    print(f"## {title}")
    print(json.dumps(value, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--company", required=True, help="AutoCount company id (its write connection must be db3)")
    parser.add_argument("--spo", type=int, required=True, help="SPO DocKey")
    parser.add_argument("--look", action="store_true", help="read the SPO and stop (no write)")
    parser.add_argument("--line", type=int, help="SPO DtlKey to split")
    parser.add_argument("--from-po", type=int, help="PO-A DocKey (the line's PO now; the move back goes there)")
    parser.add_argument("--to-po", type=int, help="PO-B DocKey")
    parser.add_argument("--to-line", type=int, help="PO-B DtlKey")
    parser.add_argument("--qty", type=Decimal, help="take for the split (below the line's open qty)")
    args = parser.parse_args(argv)
    if not args.look and None in (args.line, args.from_po, args.to_po, args.to_line, args.qty):
        parser.error("--line, --from-po, --to-po, --to-line and --qty are needed unless --look")

    from app.database import SessionLocal
    import modules.autocount.services  # noqa: F401  (import order)
    from modules.autocount.models import AcApiCallLog, AcCompany
    from modules.autocount.write_back import capabilities
    from modules.autocount.write_back.operations import OperationService, SPO_MOVE

    db = SessionLocal()
    try:
        company = db.query(AcCompany).filter(AcCompany.id == args.company).one_or_none()
        if company is None:
            print("company not found")
            return 2
        svc = OperationService(db, notifier=lambda event: print("needs-attention notice (not mailed):", event["op"]))
        book = svc.write_book(company)
        if book != TEST_BOOK:
            print(f"refused: the company's write book is {book!r}, this probe writes only to {TEST_BOOK}")
            return 2
        tenant = company.tenant_id

        def read(kind: str, key: int) -> Optional[Dict[str, Any]]:
            res = svc.prims.read_doc(tenant_id=tenant, company_id=company.id, kind=kind, doc_key=key)
            if res.outcome != "done":
                print(f"read {kind} {key} refused: {res.error_code}")
                return None
            return res.document

        before = read("SPO", args.spo)
        _print(f"SPO {args.spo} before", {"docNo": (before or {}).get("DocNo"), "lines": _lines(before)})
        if args.look or before is None:
            return 0

        table = dict(capabilities.VENDOR_CAPABILITIES)
        table["spo_move"] = True  # this process only
        capabilities.VENDOR_CAPABILITIES = MappingProxyType(table)

        def move(label: str, line: int, po_doc: int, po_line: int, qty: Decimal) -> Any:
            res = svc.run(tenant_id=tenant, company_id=company.id, key_id=None,
                          idempotency_key=f"probe-spo-move-{uuid.uuid4().hex[:12]}", op=SPO_MOVE,
                          params={"spo_doc_key": args.spo, "spo_dtl_key": line, "po_doc_key": po_doc,
                                  "po_dtl_key": po_line, "qty": qty})
            calls = (db.query(AcApiCallLog).filter(AcApiCallLog.operation_id == res.operation_id)
                     .order_by(AcApiCallLog.created_at).all()) if res.operation_id else []
            _print(label, {
                "operationId": res.operation_id, "outcome": res.outcome, "errorCode": res.error_code,
                "warnings": res.warnings, "replacedLines": res.replaced_lines,
                "moved": (res.batch or {}).get("moved"), "remainder": (res.batch or {}).get("remainder"),
                "calls": [{"method": c.method, "path": c.path, "status": c.response_status, "outcome": c.outcome,
                           "book": c.book} for c in calls],
            })
            return res

        old = next((r for r in before.get("Details") or [] if r.get("DtlKey") == args.line), None)
        if old is None or not old.get("FromDocDtlKey"):
            print("refused: --line is not an SPO line tied to a PO row")
            return 2
        split = move("1. split", args.line, args.to_po, args.to_line, args.qty)
        after_split = read("SPO", args.spo)
        _print("SPO after split", _lines(after_split))
        if split.outcome != "done":
            return 1
        moved = split.batch["moved"]
        back = move("2. whole move back", int(moved["spoDtlKey"]), args.from_po, int(old["FromDocDtlKey"]),
                    Decimal(moved["qty"]))
        _print("SPO after whole move back", _lines(read("SPO", args.spo)))
        return 0 if back.outcome == "done" else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

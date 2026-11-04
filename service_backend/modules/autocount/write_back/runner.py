"""Scripted db3 runner + AutoCount test report (plan 55 S6, AC-55-42/50/51).

Drives each use case (C01..C12) through the same ``WriteBackService`` the
gateway uses, over the db3 write connection only (the guard runs before the
first request and on every write). Setup documents (the test PO and SPO) are
created through the guarded write client at ``NEW_PO_PATH``; their DocNos come
from the run tag and are checked absent for today first.

Evidence is sanitised at capture: vendor paths only (no scheme or host), no
keys, and only document numbers, codes and quantities from rows. Nothing but
the vendor paths, action ids and those codes can reach the report.

CLI::

    python -m modules.autocount.write_back.runner --tenant-slug <slug> \\
        --company-id <uuid> --creditor <code> --run-tag <tag> --out <path.md>
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from modules.autocount.doc_feed.clock import myt_date
from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back.client import AutoCountWriteClient, WriteTransportError
from modules.autocount.write_back.constants import (
    EDIT_PO_PATH,
    NEW_PO_PATH,
    NEW_SO_PATH,
    SO_BY_DOC_DATE_PATH,
    PO_BY_DOC_DATE_PATH,
)
from modules.autocount.write_back import guard
from modules.autocount.write_back.guard import WriteNotAllowed
from modules.autocount.write_back.payloads import header_of, so_header_of
from modules.autocount.write_back.operations import OperationService
from modules.autocount.write_back.primitives import PrimitiveResult, PrimitiveService, vendor_message
from modules.autocount.write_back.pull_docs import (
    MODE_DOC_DATE,
    PullDocsResult,
    pull_documents,
    write_base_url,
)
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from modules.autocount.write_back.service import WriteActionResult, WriteBackService

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, object]
Row = Dict[str, object]

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"

# The real db3 documents the cases act on (plan 55 section 3 evidence).
REAL_PO_NO = "202602-S0007"
REAL_PO_DOC_KEY = 12008
REAL_SO_DOC_KEY = 11988
FREE_PO_ROW = 12009  # SRTKS7090, qty 1, unlinked
COVERED_SO_ROW = 11996  # qty 9, fully covered by PO row 12015
SO_ROW_QTY_2_SIDE = 11990  # SRTKS7090
LINKED_PO_ROW = 12013  # linked to SO row 11993, qty 10
LINKED_SO_ROW = 11993
BASELINE_FROM = date(2026, 1, 26)  # SO389293 DocDate
BASELINE_TO = date(2026, 2, 4)  # PO 202602-S0007 DocDate
STALE_STAMP = "1900-01-01T00:00:00.00"
ROW_ALREADY_AT_LOCATION_CODE = "ROW_ALREADY_AT_LOCATION"
ITEM = "SRTKT38SS"
DEFAULT_DEBTOR = "300-S057"

# Header fields kept as evidence of a create: codes and numbers only, never names.
_EVIDENCE_HEADER = ("DocNo", "DocDate", "CreditorCode", "DebtorCode", "ShippingPO")
_ROW_FIELDS = (
    "DtlKey", "ItemCode", "Location", "UOM", "Qty",
    "FromSODtlKey", "FromDocType", "FromDocNo", "FromDocDtlKey",
)


@dataclass
class Step:
    method: str
    path: str
    status_code: Optional[int] = None
    request_json: Optional[Doc] = None
    before_rows: Optional[List[Row]] = None
    after_rows: Optional[List[Row]] = None
    note: str = ""
    response: Optional[object] = None  # the vendor answer (plan 57 cases; None for plan 55 steps)


@dataclass
class CaseResult:
    case_id: str
    title: str
    status: str = FAIL
    expected: str = ""
    observed: str = ""
    steps: List[Step] = field(default_factory=list)
    action_id: Optional[str] = None
    http_calls: int = 0  # vendor requests the case made (plan 57 cases)


@dataclass
class SuiteResult:
    run_tag: str
    cases: List[CaseResult] = field(default_factory=list)
    # plan 57: one exact, UNSCRUBBED dict per vendor write (private file, never the report)
    evidence: List[Dict[str, object]] = field(default_factory=list)


def _doc_prefix(run_tag: str) -> str:
    """``FXT-<tag>``, without doubling the prefix when the tag already carries it."""
    return run_tag if run_tag.upper().startswith("FXT-") else f"FXT-{run_tag}"


def _rows(rows: Sequence[Row]) -> List[Row]:
    return [{k: r[k] for k in _ROW_FIELDS if k in r} for r in rows]


def _num(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


class _Run:
    """One suite run: shared handles, per-case state."""

    def __init__(
        self,
        db: Session,
        tenant_id: str,
        company: AcCompany,
        base_url: str,
        creditor_code: str,
        debtor_code: str,
        run_tag: str,
        client_factory: Callable[[str], AutoCountWriteClient],
        reader_factory: Callable[[str], AutoCountDocReader],
        sink_factory: Optional[Callable[..., object]],
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.company = company
        self.base_url = base_url
        self.creditor = creditor_code
        self.debtor = debtor_code
        self.so_no = f"{_doc_prefix(run_tag)}-SO"
        self.so_doc: Optional[Doc] = None
        self.tag = run_tag
        self.client_factory = client_factory
        self.reader_factory = reader_factory
        self.sink_factory = sink_factory
        self.service = WriteBackService(
            db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory,
        )
        self.today = myt_date(datetime.now(timezone.utc))
        self.po_no = f"{_doc_prefix(run_tag)}-1"
        self.spo_no = f"{_doc_prefix(run_tag)}-S1"
        self.results: Dict[str, CaseResult] = {}
        self.po_doc: Optional[Doc] = None
        self.big_key: int = 0

    # ── helpers ──────────────────────────────────────────────────────────────

    def _pull(self, d_from: date, d_to: date) -> PullDocsResult:
        return pull_documents(
            self.db, tenant_id=self.tenant_id, company_id=self.company.id,
            date_from=d_from, date_to=d_to, mode=MODE_DOC_DATE,
            reader_factory=self.reader_factory, sink_factory=self.sink_factory,
        )

    def _find_doc(self, doc_no: str, kind: str = "PO") -> Optional[Doc]:
        self.db.commit()  # no transaction open during a GET
        reader = self.reader_factory(self.base_url)
        for doc in reader.list_day(kind, self.today, by_last_modified=False):
            if doc.get("DocNo") == doc_no:
                return doc
        return None

    def _action(self, result: WriteActionResult) -> Optional[AcWriteAction]:
        if not result.action_id:
            return None
        return (
            self.db.query(AcWriteAction)
            .filter(
                AcWriteAction.tenant_id == self.tenant_id,
                AcWriteAction.id == result.action_id,
            )
            .first()
        )

    def _put_steps(self, row: Optional[AcWriteAction]) -> List[Step]:
        """One PUT step per write recorded on the action (one body, or a list of
        two for a split with its location move), with the touched rows before
        and after each write. Only codes, quantities and doc numbers are kept."""
        if row is None or not row.request_json:
            return []
        bodies = row.request_json if isinstance(row.request_json, list) else [row.request_json]
        afters = row.after_json if isinstance(row.after_json, list) else [row.after_json]
        responses = row.response_json if isinstance(row.response_json, list) else [row.response_json]
        previous: Doc = row.before_json or {}
        steps: List[Step] = []
        for index, body in enumerate(bodies):
            sent = body.get("Details") or []
            touched = {r.get("DtlKey") for r in sent if r.get("DtlKey")}
            before = previous.get("Details") or []
            after_doc: Doc = (afters[index] if index < len(afters) else None) or {}
            after = after_doc.get("Details") or []
            before_keys = {r.get("DtlKey") for r in before}
            reply = responses[index] if index < len(responses) else None
            statuses = row.response_status if isinstance(row.response_status, list) else [row.response_status]
            status = statuses[index] if index < len(statuses) else None
            if isinstance(reply, dict) and "error" in reply:
                status = None
            steps.append(Step(
                "PUT", EDIT_PO_PATH, status,
                {"DocKey": body.get("DocKey"), "DocNo": body.get("DocNo"), "Details": _rows(sent)},
                _rows([r for r in before if r.get("DtlKey") in touched]),
                _rows([r for r in after if r.get("DtlKey") in touched or r.get("DtlKey") not in before_keys]),
            ))
            if after_doc:
                previous = after_doc
        return steps

    def _service_case(
        self, case: CaseResult, result: WriteActionResult, outcome: str, code: Optional[str] = None
    ) -> bool:
        """Record a service answer on the case; True when it is the expected one."""
        row = self._action(result)
        case.steps.extend(self._put_steps(row))
        case.action_id = result.action_id
        case.observed = result.outcome + (f" {result.error_code}" if result.error_code else "")
        return result.outcome == outcome and (code is None or result.error_code == code)

    def _setup_post(
        self, case: CaseResult, body: Doc, doc_no: str, *, kind: str = "PO"
    ) -> Optional[Doc]:
        """Check the DocNo is absent today, POST the document (PO or SO create
        door), read it back by DocNo."""
        post_path = NEW_SO_PATH if kind == "SO" else NEW_PO_PATH
        get_path = SO_BY_DOC_DATE_PATH if kind == "SO" else PO_BY_DOC_DATE_PATH
        existing = self._find_doc(doc_no, kind)
        case.steps.append(Step("GET", get_path, 200, note=f"{doc_no} absent" if existing is None else f"{doc_no} present"))
        if existing is not None:
            case.observed = f"{doc_no} already exists for today; pick another run tag"
            return None
        self.db.commit()
        try:
            response = self.client_factory(self.base_url).post(post_path, body)
        except WriteTransportError as exc:
            case.observed = f"create failed {exc.code}"
            return None
        sent = {k: body[k] for k in _EVIDENCE_HEADER if k in body}
        sent["Details"] = _rows(body["Details"])  # type: ignore[arg-type]
        case.steps.append(Step("POST", post_path, response.status_code, sent))
        if not response.ok:
            case.observed = f"create refused by the vendor, status {response.status_code}"
            return None
        doc = self._find_doc(doc_no, kind)
        if doc is None:
            case.observed = f"{doc_no} not found after create"
        else:
            case.steps[-1].after_rows = _rows(doc.get("Details") or [])  # type: ignore[arg-type]
        return doc

    def _skip(self, case: CaseResult, prereq: str) -> bool:
        prior = self.results.get(prereq)
        if prior is not None and prior.status == PASS:
            return False
        case.status = SKIPPED
        case.observed = f"prerequisite {prereq} did not pass"
        return True

    def _create_body(
        self, case: CaseResult, doc_no: str, specs: Sequence[Doc], *, spo: bool
    ) -> Optional[Doc]:
        """A full create body: header from the creditor's existing db3 PO (through
        the header whitelist, new DocNo and DocDate, no DocKey), rows with the
        documented POST fields, description / UOM from the SO row of the item."""
        self.db.commit()
        reader = self.reader_factory(self.base_url)
        template = next(
            (d for d in reader.list_day("PO", BASELINE_TO, by_last_modified=False)
             if d.get("DocNo") == REAL_PO_NO and d.get("CreditorCode") == self.creditor),
            None,
        )
        if template is None:
            case.observed = f"no existing PO of the creditor to take the header from ({REAL_PO_NO})"
            return None
        so_doc = reader.get_document("SO", REAL_SO_DOC_KEY, BASELINE_FROM)
        so_rows = {r.get("ItemCode"): r for r in so_doc.get("Details") or []}  # type: ignore[union-attr]
        delivery = f"{self.today.isoformat()}T00:00:00"
        rows: List[Doc] = []
        for spec in specs:
            source = so_rows.get(spec["ItemCode"])
            if source is None:
                case.observed = "no SO row for the test item"
                return None
            rows.append({
                "ItemCode": spec["ItemCode"], "Location": spec["Location"],
                "Description": source.get("Description"), "ProjNo": "",
                "UOM": source.get("UOM"), "UserUOM": source.get("UOM"),
                "Qty": spec["Qty"], "FOCQty": 0, "UnitPrice": 1.0, "Discount": "",
                "TaxCode": "", "DeliveryDate": delivery, "Desc2": "",
                "FromDocType": spec.get("FromDocType", ""), "FromDocNo": spec.get("FromDocNo", ""),
                "FromDocDtlKey": spec.get("FromDocDtlKey", 0), "FullTransferOption": " ",
                "FullTransferFromDocList": "",
            })
        body: Doc = {k: v for k, v in header_of(template).items() if k != "DocKey"}
        body.update(DocNo=doc_no, DocDate=delivery, ShippingPO="T" if spo else "F", Details=rows)
        return body

    # ── cases ────────────────────────────────────────────────────────────────

    def c00(self, case: CaseResult) -> None:
        case.expected = f"test SO {self.so_no} created with three SRTKT38SS rows at BRW-AM (10, 5 and 10)"
        self.db.commit()
        reader = self.reader_factory(self.base_url)
        template = reader.get_document("SO", REAL_SO_DOC_KEY, BASELINE_FROM)
        item_rows = {r.get("ItemCode"): r for r in template.get("Details") or []}  # type: ignore[union-attr]
        source = item_rows.get(ITEM)
        if source is None:
            case.observed = "no SO row for the test item to copy from"
            return
        delivery = f"{self.today.isoformat()}T00:00:00"
        rows: List[Doc] = [
            {
                "ItemCode": ITEM, "Location": "BRW-AM", "Description": source.get("Description"),
                "YourPONo": "", "ProjNo": "", "UOM": source.get("UOM"), "UserUOM": source.get("UOM"),
                "Qty": qty, "FOCQty": 0, "UnitPrice": 1.0, "Discount": "", "TaxCode": "",
                "DeliveryDate": delivery, "Desc2": "", "FromDocType": "", "FromDocNo": "",
                "FromDocDtlKey": 0, "FullTransferOption": " ", "FullTransferFromDocList": "",
            }
            for qty in (10, 5, 10)
        ]
        body: Doc = {k: v for k, v in so_header_of(template).items() if k != "DocKey"}
        if body.get("DebtorCode") != self.debtor:
            body.pop("DebtorName", None)  # the template's name belongs to another debtor
        body.update(DocNo=self.so_no, DocDate=delivery, DebtorCode=self.debtor, Details=rows)
        doc = self._setup_post(case, body, self.so_no, kind="SO")
        if doc is None:
            return
        read_back = doc.get("Details") or []
        if len(read_back) != 3:  # type: ignore[arg-type]
            case.observed = f"rows dropped: sent 3, read back {len(read_back)}"  # type: ignore[arg-type]
            return
        self.so_doc = doc
        case.status = PASS
        case.observed = f"created {self.so_no} with 3 rows"

    def c01(self, case: CaseResult) -> None:
        case.expected = "test PO created with two SRTKT38SS rows (50 and 10 at HQ)"
        baseline = self._pull(BASELINE_FROM, BASELINE_TO)  # SO days first, then PO days
        case.steps.append(Step("GET", PO_BY_DOC_DATE_PATH, 200, note=f"baseline pull docs={baseline.docs_seen}"))
        if baseline.failed:
            case.observed = f"baseline pull failed {baseline.error_code}"
            return
        body = self._create_body(
            case, self.po_no,
            [{"ItemCode": ITEM, "Qty": 50, "Location": "HQ"}, {"ItemCode": ITEM, "Qty": 10, "Location": "HQ"}],
            spo=False,
        )
        if body is None:
            return
        doc = self._setup_post(case, body, self.po_no)
        if doc is None:
            return
        read_back = len(doc.get("Details") or [])  # type: ignore[arg-type]
        if read_back != 2:
            case.observed = f"rows dropped: sent 2, read back {read_back}"
            return
        if doc.get("ShippingPO") == "T":
            case.observed = "created document reads back as an SPO"
            return
        self.po_doc = doc
        case.status = PASS
        case.observed = f"created {self.po_no} with 2 rows"

    def c02(self, case: CaseResult) -> None:
        case.expected = "SO days then PO days pulled; the test PO is staged"
        if self._skip(case, "C00") or self._skip(case, "C01"):
            return
        result = self._pull(self.today, self.today)
        case.steps.append(Step("GET", PO_BY_DOC_DATE_PATH, 200, note=f"docs={result.docs_seen} staged={result.staged}"))
        case.observed = f"docs_seen={result.docs_seen} staged={result.staged} pushed={result.pushed}"
        if not result.failed and result.docs_seen > 0:
            case.status = PASS
        else:
            case.observed += f" failed {result.error_code or ''}".rstrip()

    def _test_rows(self) -> List[Row]:
        return list((self.po_doc or {}).get("Details") or [])  # type: ignore[arg-type]

    def _so_row(self, index: int) -> int:
        return int((self.so_doc or {}).get("Details")[index]["DtlKey"])  # type: ignore[index]

    def _so_key(self) -> int:
        return int((self.so_doc or {})["DocKey"])  # type: ignore[arg-type]

    def _linked_new_row(self, doc: Optional[Doc], so_dtl_key: int) -> Optional[Row]:
        for r in (doc or {}).get("Details") or []:  # type: ignore[union-attr]
            if r.get("FromSODtlKey") == so_dtl_key:
                return r
        return None

    def c03(self, case: CaseResult) -> None:
        case.expected = "split in two writes: 40 stay at HQ, a new 10 row linked to SO row 11989 and moved to BRW-AM"
        if self._skip(case, "C02"):
            return
        big = next(r for r in self._test_rows() if _num(r.get("Qty")) == 50)
        self.big_key = int(big["DtlKey"])  # type: ignore[arg-type]
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=self.big_key,  # type: ignore[index,arg-type]
            so_doc_key=self._so_key(), so_dtl_key=self._so_row(0), qty=Decimal(10),
        )
        if self._service_case(case, result, "done") and result.error_code is None:
            if self._linked_new_row(result.document, self._so_row(0)) is not None:
                self.po_doc = result.document
                case.status = PASS

    def c04(self, case: CaseResult) -> None:
        case.expected = "whole-row link refused: the vendor does not apply an edit of an existing row (VENDOR_UNSUPPORTED)"
        if self._skip(case, "C03"):
            return
        small = next(r for r in self._test_rows() if _num(r.get("Qty")) == 10 and not r.get("FromSODtlKey"))
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(small["DtlKey"]),  # type: ignore[index,arg-type]
            so_doc_key=self._so_key(), so_dtl_key=self._so_row(2), qty=Decimal(10),
        )
        if self._service_case(case, result, "refused", "VENDOR_UNSUPPORTED"):
            case.status = PASS

    def _refusal(self, case: CaseResult, code: str, **link: object) -> None:
        result = self.service.link(tenant_id=self.tenant_id, company_id=self.company.id, **link)  # type: ignore[arg-type]
        if self._service_case(case, result, "refused", code):
            case.status = PASS

    def c05(self, case: CaseResult) -> None:
        case.expected = "link refused: the SO row is already covered (QTY_ABOVE_OUTSTANDING)"
        if self._skip(case, "C03"):
            return
        self._refusal(
            case, "QTY_ABOVE_OUTSTANDING", po_doc_key=int(self.po_doc["DocKey"]),  # type: ignore[index,arg-type]
            po_dtl_key=self.big_key, so_doc_key=self._so_key(),
            so_dtl_key=self._so_row(0), qty=Decimal(1),
        )

    def c06(self, case: CaseResult) -> None:
        case.expected = "link refused: quantity above the PO row (QTY_ABOVE_FREE)"
        self._refusal(
            case, "QTY_ABOVE_FREE", po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=FREE_PO_ROW,
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=SO_ROW_QTY_2_SIDE, qty=Decimal(2),
        )

    def c07(self, case: CaseResult) -> None:
        case.expected = f"unlink of {REAL_PO_NO} row {LINKED_PO_ROW} refused: the vendor does not apply it (VENDOR_UNSUPPORTED), nothing sent"
        result = self.service.unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=LINKED_PO_ROW,
        )
        if self._service_case(case, result, "refused", "VENDOR_UNSUPPORTED"):
            case.status = PASS

    def c08(self, case: CaseResult) -> None:
        case.expected = "second split of the 40 row: 5 linked to SO row 11992 and moved to BRW-AM"
        if self._skip(case, "C03"):
            return
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=self.big_key,  # type: ignore[index,arg-type]
            so_doc_key=self._so_key(), so_dtl_key=self._so_row(1), qty=Decimal(5),
        )
        if self._service_case(case, result, "done") and result.error_code is None:
            if self._linked_new_row(result.document, self._so_row(1)) is not None:
                self.po_doc = result.document
                case.status = PASS

    def c09(self, case: CaseResult) -> None:
        case.expected = "stale document refused (DOC_STALE)"
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=FREE_PO_ROW, so_doc_key=REAL_SO_DOC_KEY,
            so_dtl_key=SO_ROW_QTY_2_SIDE, qty=Decimal(1), expected_last_modified=STALE_STAMP,
        )
        if self._service_case(case, result, "refused", "DOC_STALE"):
            case.status = PASS

    def c10(self, case: CaseResult) -> None:
        case.expected = "SPO unlink refused: the vendor does not apply it (VENDOR_UNSUPPORTED), nothing sent"
        if self._skip(case, "C01"):
            return
        result = self.service.spo_unlink(
            tenant_id=self.tenant_id, company_id=self.company.id, spo_doc_key=1, spo_dtl_key=1,
        )
        if self._service_case(case, result, "refused", "VENDOR_UNSUPPORTED"):
            case.status = PASS

    def c11(self, case: CaseResult) -> None:
        case.expected = "relocate of the C08 row, already at its SO location, is refused (ROW_ALREADY_AT_LOCATION)"
        if self._skip(case, "C08"):
            return
        moved = self._linked_new_row(self.po_doc, self._so_row(1))
        if moved is None:
            case.observed = "C08 left no linked row"
            return
        result = self.service.relocate(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(moved["DtlKey"]),  # type: ignore[index,arg-type]
        )
        if self._service_case(case, result, "refused", ROW_ALREADY_AT_LOCATION_CODE):
            case.status = PASS

    def c12(self, case: CaseResult) -> None:
        case.expected = "a client for another book is refused at construction with no request (WRITE_NOT_ALLOWED)"
        other = self.base_url.rstrip("/").rsplit("/", 1)[0] + "/db1"
        try:
            self.client_factory(other)
        except WriteNotAllowed as exc:
            case.observed = f"refused {exc.code}, 0 requests"
            case.status = PASS
            return
        case.observed = "client for the other book was constructed"


_CASES = (
    ("C00", "Create the test SO", "c00"),
    ("C01", "Create the test PO", "c01"),
    ("C02", "Pull SO then PO into staging", "c02"),
    ("C03", "Link with split", "c03"),
    ("C04", "Whole-row link refused by the capability gate", "c04"),
    ("C05", "Over-link refused", "c05"),
    ("C06", "Quantity above the PO row refused", "c06"),
    ("C07", "Unlink refused by the capability gate", "c07"),
    ("C08", "Second split of the 40 row", "c08"),
    ("C09", "Stale document refused", "c09"),
    ("C10", "SPO unlink refused by the capability gate", "c10"),
    ("C11", "Relocate of a row already at its location", "c11"),
    ("C12", "Other book refused with no request", "c12"),
)


def run_db3_suite(
    db: Session,
    *,
    tenant_id: str,
    company_id: str,
    creditor_code: str,
    run_tag: str,
    debtor_code: str = DEFAULT_DEBTOR,
    client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
    reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
    sink_factory: Optional[Callable[..., object]] = None,
) -> SuiteResult:
    """Run C01..C12 in order. Refuses to start (``WriteNotAllowed`` /
    ``WriteDisabled``) before any request when the company's write connection is
    not db3. A case fault is recorded as FAIL, never raised."""
    company = CompanyRepository(db).get(tenant_id, company_id)
    from modules.autocount.write_back.pull_docs import WriteDisabled

    if company is None:
        raise WriteDisabled()
    base_url = write_base_url(db, company)  # resolves WITH tenant_id and runs the db3 guard
    guard.assert_test_company(db, tenant_id, company.id)  # AC-57-22: before any request
    run = _Run(
        db, tenant_id, company, base_url, creditor_code, debtor_code, run_tag,
        client_factory or AutoCountWriteClient, reader_factory or AutoCountDocReader, sink_factory,
    )
    suite = SuiteResult(run_tag=run_tag)
    for case_id, title, method in _CASES:
        case = CaseResult(case_id, title)
        try:
            getattr(run, method)(case)
        except (DocReadError, WriteTransportError, WriteNotAllowed, KeyError, StopIteration, TypeError) as exc:
            case.status = FAIL
            case.observed = f"{case.observed} {type(exc).__name__}".strip()
        except Exception as exc:  # noqa: BLE001 - one case never stops the suite
            logger.exception("write-back runner case %s failed", case_id)
            case.status = FAIL
            case.observed = f"{case.observed} {type(exc).__name__}".strip()
        db.rollback()
        run.results[case_id] = case
        suite.cases.append(case)
    return suite


# ── report ───────────────────────────────────────────────────────────────────


def _dump(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _render_step(step: Step) -> List[str]:
    status = f" -> {step.status_code}" if step.status_code is not None else ""
    lines = [f"- {step.method} {step.path}{status}" + (f" ({step.note})" if step.note else "")]
    if step.request_json is not None:
        lines.append(f"  - request: `{_dump(step.request_json)}`")
    if step.response is not None:
        lines.append(f"  - answer: `{_dump(step.response)}`")
    if step.before_rows is not None:
        lines.append(f"  - before: `{_dump(step.before_rows)}`")
    if step.after_rows is not None:
        lines.append(f"  - after: `{_dump(step.after_rows)}`")
    return lines


def render_report(result: SuiteResult, *, run_date: date) -> str:
    """Markdown test report. Only vendor paths, document numbers, codes and
    action ids appear (the evidence was sanitised at capture)."""
    counts = {s: sum(1 for c in result.cases if c.status == s) for s in (PASS, FAIL, SKIPPED)}
    out = [
        f"# AutoCount write-back test report {run_date.isoformat()}",
        "",
        f"Book: db3. Run tag: {result.run_tag}. "
        f"PASS {counts[PASS]}, FAIL {counts[FAIL]}, SKIPPED {counts[SKIPPED]}.",
        "",
    ]
    for case in result.cases:
        out += [f"## {case.case_id} {case.title}: {case.status}", ""]
        out.append(f"- Expected: {case.expected}")
        out.append(f"- Observed: {case.observed}")
        if case.action_id:
            out.append(f"- Action: {case.action_id}")
        out.append("")
        for step in case.steps:
            out += _render_step(step)
        out.append("")
    return "\n".join(out)


# ── plan 57: Quotation / Sales Order suite (Q01..Q09) ────────────────────────

_SCRUB_KEYS = re.compile(
    r"^(DebtorName|InvAddr\d|DeliverAddr\d|Phone\d?|Fax\d?|DeliverPhone\d?|DeliverFax\d?|Attention|DeliverContact|SalesAgent|RefDocNo|ShipInfo|CreditorName|Remark\d|Note|CreatedUserID|LastModifiedUserID)$"
)


def _scrub(value: object) -> object:
    """A deep copy with customer name, address, phone and contact values replaced
    (keys and codes stay): the report is shareable, the evidence file is not."""
    if isinstance(value, dict):
        return {k: ("[scrubbed]" if _SCRUB_KEYS.match(str(k)) and v not in (None, "") else _scrub(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class _Tap:
    """Counts every vendor request and keeps every write exactly as sent / answered."""

    def __init__(self) -> None:
        self.http = 0
        self.writes: List[Dict[str, object]] = []


class _TapClient:
    def __init__(self, inner: AutoCountWriteClient, tap: _Tap) -> None:
        self._inner, self._tap = inner, tap

    def _send(self, method: str, path: str, body: object):
        self._tap.http += 1
        entry: Dict[str, object] = {"method": method, "path": path, "requestBody": body}
        self._tap.writes.append(entry)
        try:
            response = getattr(self._inner, method.lower())(path, body)
        except WriteTransportError as exc:
            entry.update(responseStatus=None, responseBody={"error": exc.code})
            raise
        entry.update(responseStatus=response.status_code, responseBody=response.body)
        return response

    def post(self, path: str, body: object):
        return self._send("POST", path, body)

    def put(self, path: str, body: object):
        return self._send("PUT", path, body)

    def delete(self, path: str, body: object):
        return self._send("DELETE", path, body)


class _TapReader:
    def __init__(self, inner: AutoCountDocReader, tap: _Tap) -> None:
        self._inner, self._tap = inner, tap

    def get_document(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.get_document(*args, **kwargs)

    def find_by_doc_no(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.find_by_doc_no(*args, **kwargs)

    def list_day(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.list_day(*args, **kwargs)


_Q_ITEM = {"ItemCode": ITEM, "UOM": "UNIT", "Description": ITEM, "Location": "HQ", "UnitPrice": 126.0}
_Q_CASES = (
    ("Q01", "Create a quotation (AutoCount numbers it, and an explicit number)", "q01"),
    ("Q02", "Edit the quotation: header, quantity, price, discount, location", "q02"),
    ("Q03", "Add a line to the quotation, then move the first line", "q03"),
    ("Q04", "Create a sales order from a quotation row", "q04"),
    ("Q05", "Edit the sales order and add a line", "q05"),
    ("Q06", "Cancel the quotation refused (no AutoCount support yet)", "q06"),
    ("Q07", "Cancel the sales order refused (no AutoCount support yet)", "q07"),
    ("Q08", "Delete a sales order line refused (no AutoCount support yet)", "q08"),
    ("Q09", "Link, unlink and relink refused while delete is off", "q09"),
)


class _QtRun:
    def __init__(self, db: Session, tenant_id: str, company: AcCompany, base_url: str, debtor: str,
                 run_tag: str, header_extra: Dict[str, object], client_factory, reader_factory,
                 sink_factory) -> None:
        self.db, self.tenant_id, self.company, self.debtor, self.tag = db, tenant_id, company, debtor, run_tag
        self.base_url = base_url
        self.extra = dict(header_extra)
        self.tap = _Tap()
        wrapped_client = lambda url: _TapClient(client_factory(url), self.tap)  # noqa: E731
        wrapped_reader = lambda url: _TapReader(reader_factory(url), self.tap)  # noqa: E731
        self.prims = PrimitiveService(db, client_factory=wrapped_client, reader_factory=wrapped_reader,
                                      sink_factory=sink_factory)
        self.ops = OperationService(db, client_factory=wrapped_client, reader_factory=wrapped_reader,
                                    sink_factory=sink_factory)
        self.today = myt_date(datetime.now(timezone.utc))
        self.evidence: List[Dict[str, object]] = []
        self.qt_auto: Optional[PrimitiveResult] = None
        self.qt: Optional[PrimitiveResult] = None
        self.so: Optional[PrimitiveResult] = None
        self.case_id = ""
        self._http_before = 0

    # ── helpers ──────────────────────────────────────────────────────────────

    def _args(self, kind: str) -> Dict[str, object]:
        return {"tenant_id": self.tenant_id, "company_id": self.company.id, "kind": kind}

    def _header(self, **over: object) -> Dict[str, object]:
        head: Dict[str, object] = {
            "DebtorCode": self.debtor, "DocDate": f"{self.today.isoformat()}T00:00:00",
            "DisplayTerm": "C.B.D.", "CurrencyCode": "MYR", "CurrencyRate": 1.0,
        }
        head.update(self.extra)
        head.update(over)
        return head

    def _line(self, qty: float = 1, **over: object) -> Dict[str, object]:
        row: Dict[str, object] = dict(_Q_ITEM, Qty=qty, DeliveryDate=f"{self.today.isoformat()}T00:00:00")
        row.update(over)
        return row

    def _action(self, result: PrimitiveResult) -> Optional[AcWriteAction]:
        if not result.action_id:
            return None
        return self.db.query(AcWriteAction).filter(
            AcWriteAction.tenant_id == self.tenant_id, AcWriteAction.id == result.action_id
        ).first()

    def record(self, case: CaseResult, result: PrimitiveResult, first_write: int) -> None:
        """Turn the writes the tap saw since ``first_write`` into evidence and report steps."""
        row = self._action(result)
        for entry in self.tap.writes[first_write:]:
            full = {
                "case": case.case_id, "method": entry["method"], "path": entry["path"],
                "requestBody": entry["requestBody"], "responseStatus": entry["responseStatus"],
                "responseBody": entry["responseBody"],
                "before": json.loads(json.dumps(row.before_json, default=str)) if row and row.before_json else None,
                "after": json.loads(json.dumps(row.after_json, default=str)) if row and row.after_json else None,
            }
            self.evidence.append(full)
            before = (full["before"] or {}).get("Details") if full["before"] else None  # type: ignore[union-attr]
            after = (full["after"] or {}).get("Details") if full["after"] else None  # type: ignore[union-attr]
            case.steps.append(Step(
                str(entry["method"]), str(entry["path"]), entry["responseStatus"],  # type: ignore[arg-type]
                _scrub(entry["requestBody"]),  # type: ignore[arg-type]
                _rows(before) if before else None, _rows(after) if after else None,  # type: ignore[arg-type]
                response=self._report_answer(entry),
            ))
        case.action_id = result.action_id

    def _report_answer(self, entry: Dict[str, object]) -> object:
        """The answer shown in the report: a success as it came (scrubbed); a failure as
        its redacted first line only (an IIS page or a stack never reaches the report)."""
        status = entry["responseStatus"]
        if isinstance(status, int) and 200 <= status < 300:
            return _scrub(entry["responseBody"])
        # AutoCount's own message when there is one; else the status only (never a stack,
        # an exception type or the raw body)
        return vendor_message(entry["responseBody"], self.base_url) or f"status {status}"

    def call(self, case: CaseResult, fn) -> PrimitiveResult:
        start = len(self.tap.writes)
        result = fn()
        self.record(case, result, start)
        return result

    @staticmethod
    def line_of(result: Optional[PrimitiveResult], index: int = 0) -> int:
        return int(((result.document or {}).get("Details") or [])[index]["DtlKey"])  # type: ignore[union-attr]

    def _note(self, result: PrimitiveResult) -> str:
        return result.outcome + (f" {result.error_code}" if result.error_code else "")

    # ── cases ────────────────────────────────────────────────────────────────

    def q01(self, case: CaseResult) -> None:
        case.expected = "a quotation created with AutoCount's own number, and one with an FXT number"
        auto = self.call(case, lambda: self.prims.create_doc(
            **self._args("QT"), header=self._header(), lines=[self._line(1)]))
        explicit = self.call(case, lambda: self.prims.create_doc(
            **self._args("QT"), header=self._header(DocNo=f"{_doc_prefix(self.tag)}-QT"), lines=[self._line(1)]))
        case.observed = f"auto {self._note(auto)} {auto.doc_no or ''}; explicit {self._note(explicit)} {explicit.doc_no or ''}".strip()
        if auto.outcome == "done":
            self.qt_auto = auto
        if explicit.outcome == "done":
            self.qt = explicit
        if auto.outcome == "done" and explicit.outcome == "done":
            case.status = PASS

    def _qt_ready(self, case: CaseResult) -> Optional[PrimitiveResult]:
        if self.qt is None:
            case.status, case.observed = SKIPPED, "no quotation was created"
        return self.qt

    def q02(self, case: CaseResult) -> None:
        case.expected = "header text, quantity, unit price, discount and location all read back changed"
        qt = self._qt_ready(case)
        if qt is None:
            return
        res = self.call(case, lambda: self.prims.edit_doc(
            **self._args("QT"), doc_key=int(qt.doc_key or 0), doc_date=self.today,
            header_changes={"Ref": f"{self.tag} edited"},
            line_changes=[{"DtlKey": self.line_of(qt), "Qty": 2, "UnitPrice": 850.0, "Discount": "5%",
                           "Location": "HQ"}]))
        case.observed = self._note(res) + (f" {res.message}" if res.message else "")
        case.status = PASS if res.outcome == "done" else FAIL

    def q03(self, case: CaseResult) -> None:
        case.expected = "one new line read back with its own DtlKey"
        qt = self._qt_ready(case)
        if qt is None:
            return
        res = self.call(case, lambda: self.prims.add_line(
            **self._args("QT"), doc_key=int(qt.doc_key or 0), doc_date=self.today, line=self._line(3)))
        moved = self.call(case, lambda: self.prims.edit_doc(
            **self._args("QT"), doc_key=int(qt.doc_key or 0), doc_date=self.today, header_changes={},
            line_changes=[{"DtlKey": self.line_of(qt), "Location": "BRW-AM"}]))
        case.observed = f"add {self._note(res)}" + (f" new row {res.new_dtl_key}" if res.new_dtl_key else "") + (
            f"; move {self._note(moved)}")
        case.status = PASS if res.outcome == "done" and moved.outcome == "done" else FAIL

    def q04(self, case: CaseResult) -> None:
        case.expected = "sales order created from the quotation row; the row link is unconfirmed (AutoCount reads it back as 0)"
        qt = self._qt_ready(case)
        if qt is None:
            return
        # db3 (live run 4 Nov): a row that carries a quotation link is dropped unless the
        # vendor-shaped transfer fields ride along, and it then takes the quotation row's
        # unit price and location (Q02 / Q03 left 850.0 at BRW-AM), so those are sent as they are.
        line = self._line(1, FromDocType="QT", FromDocNo=qt.doc_no, FromDocDtlKey=self.line_of(qt),
                          UnitPrice=850.0, Location="BRW-AM",
                          YourPONo="", ProjNo="", FOCQty=0, Discount="", TaxCode="", Desc2="",
                          FullTransferOption=" ", FullTransferFromDocList="")
        res = self.call(case, lambda: self.prims.create_doc(
            **self._args("SO"), header=self._header(DocNo=f"{_doc_prefix(self.tag)}-SO"), lines=[line]))
        case.observed = self._note(res) + (f" warnings {','.join(res.warnings)}" if res.warnings else "")
        if res.outcome == "done":
            self.so = res
            case.status = PASS if "QT_ROW_LINK_UNCONFIRMED" in res.warnings else FAIL
            if case.status == FAIL:
                case.observed += " (link confirmed or no warning: unexpected)"

    def q05(self, case: CaseResult) -> None:
        case.expected = "sales order edited and one line added"
        so = self.so
        if so is None:
            case.status, case.observed = SKIPPED, "no sales order was created"
            return
        edit = self.call(case, lambda: self.prims.edit_doc(
            **self._args("SO"), doc_key=int(so.doc_key or 0), doc_date=self.today,
            header_changes={"Ref": f"{self.tag} so"},
            line_changes=[{"DtlKey": self.line_of(so), "Qty": 2, "UnitPrice": 800.0}]))
        add = self.call(case, lambda: self.prims.add_line(
            **self._args("SO"), doc_key=int(so.doc_key or 0), doc_date=self.today,
            line=self._line(2, YourPONo="", ProjNo="", FOCQty=0, Discount="", TaxCode="", Desc2="",
                            FromDocType="", FromDocNo="", FromDocDtlKey=0,
                            FullTransferOption=" ", FullTransferFromDocList="")))
        case.observed = f"edit {self._note(edit)}; add {self._note(add)}"
        case.status = PASS if edit.outcome == "done" and add.outcome == "done" else FAIL

    def _refused(self, case: CaseResult, results: List[str]) -> None:
        """PASS when every answer is a VENDOR_UNSUPPORTED refusal and no request was made."""
        case.observed = "; ".join(results)
        ok = all("refused VENDOR_UNSUPPORTED" in r for r in results)
        case.status = PASS if ok and self.tap.http == self._http_before else FAIL

    def q06(self, case: CaseResult) -> None:
        case.expected = "refused VENDOR_UNSUPPORTED, no request"
        res = self.call(case, lambda: self.prims.cancel_doc(
            **self._args("QT"), doc_key=int((self.qt.doc_key if self.qt else 0) or 1)))
        self._refused(case, [f"cancel QT {self._note(res)}"])

    def q07(self, case: CaseResult) -> None:
        case.expected = "refused VENDOR_UNSUPPORTED, no request"
        res = self.call(case, lambda: self.prims.cancel_doc(
            **self._args("SO"), doc_key=int((self.so.doc_key if self.so else 0) or 1)))
        self._refused(case, [f"cancel SO {self._note(res)}"])

    def q08(self, case: CaseResult) -> None:
        case.expected = "refused VENDOR_UNSUPPORTED, no request"
        key = int((self.so.doc_key if self.so else 0) or 1)
        dtl = self.line_of(self.so) if self.so else 1
        res = self.call(case, lambda: self.prims.delete_line(**self._args("SO"), doc_key=key, dtl_key=dtl))
        self._refused(case, [f"delete line SO {self._note(res)}"])

    def q09(self, case: CaseResult) -> None:
        case.expected = "link_row, unlink_row and relink_row each refused VENDOR_UNSUPPORTED, no request"
        results: List[str] = []
        specs = (
            ("link_row", {"doc_key": 1, "dtl_key": 1, "so_doc_key": 2, "so_dtl_key": 2}),
            ("unlink_row", {"doc_key": 1, "dtl_key": 1}),
            ("relink_row", {"doc_key": 1, "dtl_key": 1, "so_doc_key": 2, "so_dtl_key": 2}),
        )
        for op, params in specs:
            out = self.ops.run(
                tenant_id=self.tenant_id, company_id=self.company.id, key_id=None,
                idempotency_key=f"{self.tag}-q09-{op}", op=op, params=params)
            results.append(f"{op} {out.outcome}" + (f" {out.error_code}" if out.error_code else ""))
        self._refused(case, results)


def run_qtso_suite(
    db: Session,
    *,
    tenant_id: str,
    company_id: str,
    debtor_code: str,
    run_tag: str,
    header_extra: Optional[Dict[str, object]] = None,
    client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
    reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
    sink_factory: Optional[Callable[..., object]] = None,
) -> SuiteResult:
    """Run Q01..Q09 through the real primitive / operation services. Refuses to
    start before any request (``WriteDisabled`` / ``WriteNotAllowed`` for the
    connection, ``WriteConnectionError`` ``WRITE_COMPANY_NOT_TEST`` for a company
    that reads SQL or holds documents staged by another job). A case fault is
    recorded as FAIL, never raised; every vendor write lands in ``evidence``."""
    from modules.autocount.write_back.pull_docs import WriteDisabled

    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        raise WriteDisabled()
    base_url = write_base_url(db, company)
    guard.assert_test_company(db, tenant_id, company.id)  # raises WriteConnectionError
    run = _QtRun(
        db, tenant_id, company, base_url, debtor_code, run_tag, header_extra or {},
        client_factory or AutoCountWriteClient, reader_factory or AutoCountDocReader, sink_factory,
    )
    suite = SuiteResult(run_tag=run_tag)
    for case_id, title, method in _Q_CASES:
        case = CaseResult(case_id, title)
        run.case_id = case_id
        run._http_before = run.tap.http
        try:
            getattr(run, method)(case)
        except Exception as exc:  # noqa: BLE001 - one case never stops the suite
            logger.exception("write-back runner case %s failed", case_id)
            case.status = FAIL
            case.observed = f"{case.observed} {type(exc).__name__}".strip()
        case.http_calls = run.tap.http - run._http_before
        db.rollback()
        suite.cases.append(case)
    suite.evidence = run.evidence
    return suite


def write_evidence(result: SuiteResult, path: str) -> None:
    """The exact, unscrubbed evidence (private): one entry per vendor write."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result.evidence, handle, indent=1, default=str)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the db3 write-back suite.")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--creditor")
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--debtor", default=DEFAULT_DEBTOR)
    parser.add_argument("--out", required=True)
    parser.add_argument("--suite", choices=("db3", "qtso"), default="db3")
    parser.add_argument("--evidence", help="qtso: path of the exact (private) evidence JSON")
    parser.add_argument("--header-extra", help="qtso: JSON file of header fields (names, addresses) to send")
    args = parser.parse_args(argv)
    if args.suite == "db3" and not args.creditor:
        parser.error("--creditor is required for the db3 suite")

    from app.database import SessionLocal
    from app.models.tenant import Tenant

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print("error: unknown tenant")
            return 2
        try:
            if args.suite == "qtso":
                extra: Dict[str, object] = {}
                if args.header_extra:
                    with open(args.header_extra, encoding="utf-8") as handle:
                        extra = json.load(handle)
                result = run_qtso_suite(
                    db, tenant_id=tenant.id, company_id=args.company_id, debtor_code=args.debtor,
                    run_tag=args.run_tag, header_extra=extra,
                )
            else:
                result = run_db3_suite(
                    db, tenant_id=tenant.id, company_id=args.company_id,
                    creditor_code=args.creditor, run_tag=args.run_tag, debtor_code=args.debtor,
                )
        except (WriteNotAllowed, Exception) as exc:  # noqa: BLE001
            print(f"error: {getattr(exc, 'code', type(exc).__name__)}")
            return 2
    today = myt_date(datetime.now(timezone.utc))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render_report(result, run_date=today))
    if args.evidence:
        write_evidence(result, args.evidence)
    for case in result.cases:
        print(f"{case.case_id} {case.status}")
    return 0 if all(c.status != FAIL for c in result.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())

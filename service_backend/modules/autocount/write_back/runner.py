"""Scripted db3 runner + AutoCount test report (plan 55 S6, AC-55-42/50/51).

Drives each use case (C00..C17) through the same services (``WriteBackService``,
``OperationService``, ``PrimitiveService``) the
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
from typing import Callable, Dict, List, Optional, Sequence, Tuple

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
from modules.autocount.write_back import auth
from modules.autocount.write_back import call_log as cl
from modules.autocount.write_back import guard
from modules.autocount.write_back.guard import WriteNotAllowed
from modules.autocount.write_back.payloads import header_of, so_header_of
from modules.autocount.write_back.operations import OperationResult, OperationService
from modules.autocount.write_back.primitives import PrimitiveResult, PrimitiveService, vendor_message
from modules.autocount.write_back.pull_docs import (
    MODE_DOC_DATE,
    PullDocsResult,
    pull_documents,
    write_auth_headers,
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
    summary: str = ""  # markdown shown under the report header (the batch suite's timing table)


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
        auth_headers: Optional[Tuple[Dict[str, str], Dict[str, str]]] = None,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.company = company
        self.base_url = base_url
        write_auth, read_auth = auth_headers or ({}, {})
        self.creditor = creditor_code
        self.debtor = debtor_code
        self.so_no = f"{_doc_prefix(run_tag)}-SO"
        self.so_doc: Optional[Doc] = None
        self.tag = run_tag
        # plan 61 section 4.8: the runner's own calls are logged with actor "runner"
        log = cl.CallLog(db.get_bind(), cl.CallContext(tenant_id, company.id, actor=cl.ACTOR_RUNNER))
        self.client_factory = lambda url: cl.attach_call_log(  # noqa: E731
            auth.attach_headers(client_factory(url), write_auth), log)
        self.reader_factory = lambda url: cl.attach_call_log(  # noqa: E731
            auth.attach_headers(reader_factory(url), read_auth), log)
        self.sink_factory = sink_factory
        self.service = WriteBackService(
            db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory, actor=cl.ACTOR_RUNNER,
        )
        # plan 61 AC-61-50: the gateway's own path (operations and primitives) on the run's documents
        self.ops = OperationService(
            db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory, actor=cl.ACTOR_RUNNER,
        )
        self.prims = PrimitiveService(
            db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory, actor=cl.ACTOR_RUNNER,
        )
        self.c07_key = 0
        self.c14_key = 0
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
            reader_factory=self.reader_factory, sink_factory=self.sink_factory, actor=cl.ACTOR_RUNNER,
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
        case.expected = ("whole-row link (plan 61 F5): the free 10 row is replaced in ONE PUT by a row "
                         "linked to the third SO row, then moved back to BRW-AM")
        if self._skip(case, "C03"):
            return
        small = next(r for r in self._test_rows() if _num(r.get("Qty")) == 10 and not r.get("FromSODtlKey"))
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(small["DtlKey"]),  # type: ignore[index,arg-type]
            so_doc_key=self._so_key(), so_dtl_key=self._so_row(2), qty=Decimal(10),
        )
        if self._service_case(case, result, "done") and result.error_code is None:
            rows = (result.document or {}).get("Details") or []  # type: ignore[union-attr]
            gone = all(r.get("DtlKey") != small["DtlKey"] for r in rows)  # type: ignore[union-attr]
            if gone and self._linked_new_row(result.document, self._so_row(2)) is not None:
                self.po_doc = result.document
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
        case.expected = f"link of {REAL_PO_NO} row {FREE_PO_ROW} refused: quantity above the PO row (QTY_ABOVE_FREE)"
        self._refusal(
            case, "QTY_ABOVE_FREE", po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=FREE_PO_ROW,
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=SO_ROW_QTY_2_SIDE, qty=Decimal(2),
        )

    def c07(self, case: CaseResult) -> None:
        case.expected = ("unlink (plan 61 F4) of the C04 row on the test PO: ONE PUT, the linked row "
                         "deleted and a normal row with the same item, qty and location added")
        if self._skip(case, "C04"):
            return
        linked = self._linked_new_row(self.po_doc, self._so_row(2))
        if linked is None:
            case.observed = "C04 left no linked row"
            return
        result = self.service.unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(linked["DtlKey"]),  # type: ignore[index,arg-type]
        )
        if self._service_case(case, result, "done") and result.error_code is None:
            rows = (result.document or {}).get("Details") or []  # type: ignore[union-attr]
            known = {r.get("DtlKey") for r in self._test_rows()}
            fresh = [r for r in rows if r.get("DtlKey") not in known]  # type: ignore[union-attr]
            if all(r.get("DtlKey") != linked["DtlKey"] for r in rows) and len(fresh) == 1:  # type: ignore[union-attr]
                self.c07_key = int(fresh[0]["DtlKey"])  # type: ignore[index]
                self.po_doc = result.document
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


    # ── plan 61 cases through the operation / primitive services (AC-61-50) ───

    def _op_steps(self, case: CaseResult, operation_id: Optional[str]) -> None:
        if not operation_id:
            return
        rows = (
            self.db.query(AcWriteAction)
            .filter(AcWriteAction.tenant_id == self.tenant_id, AcWriteAction.operation_id == operation_id)
            .order_by(AcWriteAction.created_at, AcWriteAction.id)
            .all()
        )
        for row in rows:
            case.steps.extend(self._put_steps(row))

    def _run_op(self, case: CaseResult, op: str, params: Dict[str, object]) -> OperationResult:
        out = self.ops.run(
            tenant_id=self.tenant_id, company_id=self.company.id, key_id=None,
            idempotency_key=f"{self.tag}-{case.case_id.lower()}-{op}", op=op, params=params,
        )
        self._op_steps(case, out.operation_id)
        case.observed = out.outcome + (f" {out.error_code}" if out.error_code else "") + (
            f" warnings {','.join(out.warnings)}" if out.warnings else "")
        if out.document:
            self.po_doc = out.document
        return out

    def _po_params(self, dtl_key: int, **extra: object) -> Dict[str, object]:
        return dict(doc_key=int(self.po_doc["DocKey"]), dtl_key=dtl_key, doc_date=self.today,  # type: ignore[index]
                    **extra)

    @staticmethod
    def _kept_values(new: Optional[Row], old: Row) -> bool:
        """The new row carries the old row's unit price and delivery date (the F5 restore)."""
        return new is not None and _num(new.get("UnitPrice")) == _num(old.get("UnitPrice")) and (
            str(new.get("DeliveryDate"))[:10] == str(old.get("DeliveryDate"))[:10])

    def _row(self, dtl_key: int) -> Optional[Row]:
        return next((r for r in self._test_rows() if r.get("DtlKey") == dtl_key), None)

    def c13(self, case: CaseResult) -> None:
        case.expected = ("unlink_row (operation) of the C03 row: ONE PUT, the first SO row freed; replacedLines "
                         "names the new free row, or the existing free row it merged into (plan 62 D7; "
                         "C07 uses the plan 55 service path and never merges)")
        if self._skip(case, "C08"):
            return
        linked = self._linked_new_row(self.po_doc, self._so_row(0))
        if linked is None:
            case.observed = "C03 left no linked row"
            return
        out = self._run_op(case, "unlink_row", self._po_params(int(linked["DtlKey"])))  # type: ignore[arg-type]
        if out.outcome == "done" and len(out.replaced_lines) == 1:
            case.status = PASS

    def c14(self, case: CaseResult) -> None:
        case.expected = ("link_row (operation) of the row C13 left (the C07 row; C13's unlink merges into it, plan 62 D7) "
                         "to the first SO row, for the quantity that SO row still has outstanding: one write, then the "
                         "move puts back the SO row's location and the old unit price and date")
        if self._skip(case, "C13") or self._skip(case, "C07"):
            return
        old = self._row(self.c07_key)
        if old is None:
            case.observed = "C07 left no unlinked row"
            return
        so_row = ((self.so_doc or {}).get("Details") or [{}])[0]  # type: ignore[union-attr]
        so_key = self._so_row(0)
        taken = sum((_num(r.get("Qty")) for r in self._test_rows() if r.get("FromSODtlKey") == so_key), Decimal(0))
        qty = min(_num(old.get("Qty")), _num(so_row.get("Qty")) - taken)
        if qty <= 0:
            case.observed = "the first SO row has nothing outstanding"
            return
        extra: Dict[str, object] = {} if qty == _num(old.get("Qty")) else {"qty": qty}
        before_keys = {r.get("DtlKey") for r in self._test_rows()}
        out = self._run_op(case, "link_row", self._po_params(
            self.c07_key, so_doc_key=self._so_key(), so_dtl_key=so_key, target_doc_date=self.today, **extra))
        if out.outcome != "done" or _move_warned(out.warnings):
            return
        if out.replaced_lines:  # a whole row: replaced by one linked row
            new_key: Optional[int] = out.replaced_lines[0][1]
        else:  # part of the row: the linked row is the one new row carrying the SO link
            fresh = [r for r in self._test_rows()
                     if r.get("DtlKey") not in before_keys and r.get("FromSODtlKey") == so_key]
            new_key = int(fresh[0]["DtlKey"]) if len(fresh) == 1 else None  # type: ignore[arg-type]
        new = self._row(new_key) if new_key is not None else None
        if new is not None and self._kept_values(new, old) and new.get("Location") == so_row.get("Location") \
                and _num(new.get("Qty")) == qty:
            self.c14_key = int(new_key)  # type: ignore[arg-type]
            case.status = PASS

    def c15(self, case: CaseResult) -> None:
        case.expected = ("relink_row (operation) of the C14 row to the third SO row: ONE replace PUT and the "
                         "move, unit price and delivery date kept")
        if self._skip(case, "C14"):
            return
        old = self._row(self.c14_key)
        out = self._run_op(case, "relink_row", self._po_params(
            self.c14_key, so_doc_key=self._so_key(), so_dtl_key=self._so_row(2), target_doc_date=self.today))
        if out.outcome == "done" and not _move_warned(out.warnings) and len(out.replaced_lines) == 1 and old is not None:
            new = self._row(out.replaced_lines[0][1])
            if self._kept_values(new, old) and new is not None and new.get("FromSODtlKey") == self._so_row(2):
                case.status = PASS

    def c16(self, case: CaseResult) -> None:
        case.expected = "PO delete_line (primitive) of the free C03 remainder row: ONE PUT with the row marked D"
        if self._skip(case, "C08"):
            return
        res = self.prims.delete_line(
            tenant_id=self.tenant_id, company_id=self.company.id, kind="PO",
            doc_key=int(self.po_doc["DocKey"]), dtl_key=self.big_key, doc_date=self.today)  # type: ignore[index]
        case.steps.extend(self._put_steps(self._prim_action(res)))
        case.action_id = res.action_id
        case.observed = res.outcome + (f" {res.error_code}" if res.error_code else "")
        if res.outcome == "done" and res.document is not None:
            self.po_doc = res.document
            if all(r.get("DtlKey") != self.big_key for r in self._test_rows()):
                case.status = PASS

    def c17(self, case: CaseResult) -> None:
        case.expected = "PO cancel (primitive) of the test PO: DELETE /CancelPurchaseOrderbydocno, reads back Cancelled T"
        if self._skip(case, "C01"):
            return
        res = self.prims.cancel_doc(
            tenant_id=self.tenant_id, company_id=self.company.id, kind="PO",
            doc_key=int(self.po_doc["DocKey"]), doc_date=self.today)  # type: ignore[index]
        row = self._prim_action(res)
        if row is not None and row.request_method:
            case.steps.append(Step(str(row.request_method), str(row.request_path), row.response_status))  # type: ignore[arg-type]
        case.action_id = res.action_id
        case.observed = res.outcome + (f" {res.error_code}" if res.error_code else "")
        if res.outcome == "done" and (res.document or {}).get("Cancelled") == "T":
            case.status = PASS

    def _prim_action(self, res: PrimitiveResult) -> Optional[AcWriteAction]:
        if not res.action_id:
            return None
        return self.db.query(AcWriteAction).filter(
            AcWriteAction.tenant_id == self.tenant_id, AcWriteAction.id == res.action_id).first()



def _require_test_book(base_url: str) -> None:
    """The suites write test data: only a test book, whatever the environment."""
    book = guard.book_of(base_url)
    if book not in guard.TEST_BOOKS:
        raise WriteNotAllowed(book or "")


def _move_warned(warnings: Sequence[str]) -> bool:
    """The restore move did not land (``TRANSFER_STATE_UNKNOWN`` alone is fine: db3's GET
    never shows a received quantity)."""
    return bool({"LOCATION_NOT_MOVED", "ROW_VALUES_NOT_KEPT"} & set(warnings))


_CASES = (
    ("C00", "Create the test SO", "c00"),
    ("C01", "Create the test PO", "c01"),
    ("C02", "Pull SO then PO into staging", "c02"),
    ("C03", "Link with split", "c03"),
    ("C04", "Whole-row link in one replace PUT", "c04"),
    ("C05", "Over-link refused", "c05"),
    ("C06", "Quantity above the PO row refused", "c06"),
    ("C07", "Unlink in one replace PUT", "c07"),
    ("C08", "Second split of the 40 row", "c08"),
    ("C09", "Stale document refused", "c09"),
    ("C10", "SPO unlink refused by the capability gate", "c10"),
    ("C11", "Relocate of a row already at its location", "c11"),
    ("C12", "Other book refused with no request", "c12"),
    ("C13", "Unlink through the operation layer (replace PUT)", "c13"),
    ("C14", "Link the row C13 left through the operation layer (write + restore move)", "c14"),
    ("C15", "Relink through the operation layer (replace PUT + restore move)", "c15"),
    ("C16", "Delete a PO line (one PUT, row marked D)", "c16"),
    ("C17", "Cancel the test PO", "c17"),
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
    """Run C00..C17 in order. Refuses to start (``WriteNotAllowed`` /
    ``WriteDisabled``) before any request, in every environment, when the company's
    write connection is not a test book. A case fault is recorded as FAIL, never raised."""
    company = CompanyRepository(db).get(tenant_id, company_id)
    from modules.autocount.write_back.pull_docs import WriteDisabled

    if company is None:
        raise WriteDisabled()
    base_url = write_base_url(db, company)  # resolves WITH tenant_id and runs the write guard
    _require_test_book(base_url)
    guard.assert_test_company(db, tenant_id, company.id, book=guard.book_of(base_url))  # AC-57-22: before any request
    run = _Run(
        db, tenant_id, company, base_url, creditor_code, debtor_code, run_tag,
        client_factory or AutoCountWriteClient, reader_factory or AutoCountDocReader, sink_factory,
        auth_headers=write_auth_headers(db, company),
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
    if result.summary:
        out += [result.summary, ""]
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


# ── plan 57: Quotation / Sales Order suite (Q01..Q10) ────────────────────────

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

    def attach_call_log(self, log: cl.CallLog) -> None:
        cl.attach_call_log(self._inner, log)

    def set_auth_headers(self, headers: Dict[str, str]) -> None:
        auth.attach_headers(self._inner, headers)

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

    def delete_query(self, path: str, params: Dict[str, str]):
        """Plan 61 cancel: DELETE with the query string, no body."""
        self._tap.http += 1
        entry: Dict[str, object] = {"method": "DELETE", "path": path, "requestBody": None,
                                    "requestQuery": dict(params)}
        self._tap.writes.append(entry)
        try:
            response = self._inner.delete_query(path, params)
        except WriteTransportError as exc:
            entry.update(responseStatus=None, responseBody={"error": exc.code})
            raise
        entry.update(responseStatus=response.status_code, responseBody=response.body)
        return response


class _TapReader:
    def __init__(self, inner: AutoCountDocReader, tap: _Tap) -> None:
        self._inner, self._tap = inner, tap

    def attach_call_log(self, log: cl.CallLog) -> None:
        cl.attach_call_log(self._inner, log)

    def set_auth_headers(self, headers: Dict[str, str]) -> None:
        auth.attach_headers(self._inner, headers)

    def get_document(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.get_document(*args, **kwargs)

    def find_by_doc_no(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.find_by_doc_no(*args, **kwargs)

    def get_by_doc_no(self, *args, **kwargs):
        self._tap.http += 1
        return self._inner.get_by_doc_no(*args, **kwargs)

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
    ("Q06", "Cancel the quotations: the plain one is cancelled, the transferred one refused", "q06"),
    ("Q07", "Delete a sales order line (one PUT, the row marked D)", "q07"),
    ("Q08", "Cancel the sales order", "q08"),
    ("Q09", "SPO link, unlink and relink refused (SPO stays off)", "q09"),
    ("Q10", "Delete a quotation line (one PUT, the row marked D)", "q10"),
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
                                      sink_factory=sink_factory, actor=cl.ACTOR_RUNNER)
        self.ops = OperationService(db, client_factory=wrapped_client, reader_factory=wrapped_reader,
                                    sink_factory=sink_factory, actor=cl.ACTOR_RUNNER)
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
        case.expected = ("plan 61 F9 / F11: the auto-numbered quotation cancelled (Cancelled T); the "
                         "quotation Q04 transferred into the sales order refused DOC_HAS_TRANSFERS")
        if self.qt_auto is None or self.qt is None:
            case.status, case.observed = SKIPPED, "no quotation was created"
            return
        plain = self.call(case, lambda: self.prims.cancel_doc(
            **self._args("QT"), doc_key=int(self.qt_auto.doc_key or 0), doc_date=self.today))  # type: ignore[union-attr]
        moved = self.call(case, lambda: self.prims.cancel_doc(
            **self._args("QT"), doc_key=int(self.qt.doc_key or 0), doc_date=self.today))  # type: ignore[union-attr]
        case.observed = f"plain {self._note(plain)}; transferred {self._note(moved)}"
        ok = plain.outcome == "done" and moved.error_code == "DOC_HAS_TRANSFERS"
        case.status = PASS if ok and self.so is not None else FAIL

    def q07(self, case: CaseResult) -> None:
        case.expected = "plan 61 F6: the Q05 line deleted by ONE PUT with the row marked D; the other line kept"
        so = self.so
        if so is None:
            case.status, case.observed = SKIPPED, "no sales order was created"
            return
        fresh = self.prims.read_doc(**self._args("SO"), doc_key=int(so.doc_key or 0), doc_date=self.today)
        rows = (fresh.document or {}).get("Details") or []  # type: ignore[union-attr]
        if len(rows) < 2:  # type: ignore[arg-type]
            case.status, case.observed = SKIPPED, "the sales order has fewer than two lines"
            return
        dtl = int(rows[-1]["DtlKey"])  # type: ignore[index]
        res = self.call(case, lambda: self.prims.delete_line(
            **self._args("SO"), doc_key=int(so.doc_key or 0), dtl_key=dtl, doc_date=self.today))
        case.observed = self._note(res)
        case.status = PASS if res.outcome == "done" else FAIL

    def q08(self, case: CaseResult) -> None:
        case.expected = "plan 61 F9 / F12: the sales order cancelled (DELETE by DocNo, reads back Cancelled T)"
        so = self.so
        if so is None:
            case.status, case.observed = SKIPPED, "no sales order was created"
            return
        res = self.call(case, lambda: self.prims.cancel_doc(
            **self._args("SO"), doc_key=int(so.doc_key or 0), doc_date=self.today))
        case.observed = self._note(res)
        case.status = PASS if res.outcome == "done" else FAIL

    def q09(self, case: CaseResult) -> None:
        case.expected = "spo_link_row, spo_unlink_row and spo_relink_row each refused VENDOR_UNSUPPORTED, no request (F14)"
        results: List[str] = []
        specs = (
            ("spo_link_row", {"spo_doc_key": 1, "spo_dtl_key": 1, "po_doc_key": 2, "po_dtl_key": 2}),
            ("spo_unlink_row", {"spo_doc_key": 1, "spo_dtl_key": 1}),
            ("spo_relink_row", {"spo_doc_key": 1, "spo_dtl_key": 1, "po_doc_key": 2, "po_dtl_key": 2}),
        )
        for op, params in specs:
            out = self.ops.run(
                tenant_id=self.tenant_id, company_id=self.company.id, key_id=None,
                idempotency_key=f"{self.tag}-q09-{op}", op=op, params=params)
            results.append(f"{op} {out.outcome}" + (f" {out.error_code}" if out.error_code else ""))
        self._refused(case, results)

    def q10(self, case: CaseResult) -> None:
        case.expected = "plan 61 F6: the Q03 line of the quotation deleted by ONE PUT with the row marked D"
        qt = self.qt
        if qt is None:
            case.status, case.observed = SKIPPED, "no quotation was created"
            return
        fresh = self.prims.read_doc(**self._args("QT"), doc_key=int(qt.doc_key or 0), doc_date=self.today)
        rows = (fresh.document or {}).get("Details") or []  # type: ignore[union-attr]
        if len(rows) < 2:  # type: ignore[arg-type]
            case.status, case.observed = SKIPPED, "the quotation has fewer than two lines"
            return
        dtl = int(rows[-1]["DtlKey"])  # type: ignore[index]
        res = self.call(case, lambda: self.prims.delete_line(
            **self._args("QT"), doc_key=int(qt.doc_key or 0), dtl_key=dtl, doc_date=self.today))
        case.observed = self._note(res)
        case.status = PASS if res.outcome == "done" else FAIL


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
    """Run Q01..Q10 through the real primitive / operation services. Refuses to
    start before any request, in every environment (``WriteDisabled`` /
    ``WriteNotAllowed`` for the connection or a book that is not a test book, ``WriteConnectionError`` ``WRITE_COMPANY_NOT_TEST`` for a company
    that reads SQL or holds documents staged by another job). A case fault is
    recorded as FAIL, never raised; every vendor write lands in ``evidence``."""
    from modules.autocount.write_back.pull_docs import WriteDisabled

    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        raise WriteDisabled()
    base_url = write_base_url(db, company)
    _require_test_book(base_url)
    write_auth_headers(db, company)  # an unusable API key setting refuses the run before any request
    guard.assert_test_company(db, tenant_id, company.id, book=guard.book_of(base_url))  # raises WriteConnectionError
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


# ── plan 62: PO link batch suite (B00..B06) ──────────────────────────────────

_B_CASES = (
    ("B00", "Create the test documents (3 sales orders, 1 purchase order)", "b00"),
    ("B01", "Batch of 1 SO line (sum below the row quantity: a free row stays)", "b01"),
    ("B02", "Batch of 3 SO lines across 2 sales orders (sum equals the row quantity: the row is deleted)", "b02"),
    ("B03", "Batch of 5 SO lines across 2 sales orders (sum below the row quantity)", "b03"),
    ("B04", "Today's flow: the same 3 SO lines linked one call at a time (timing baseline)", "b04"),
    ("B05", "Unlink one batch row: it merges into the free row in one PUT", "b05"),
    ("B06", "Retry rule: a refused batch, the body fixed, the SAME key resent", "b06"),
    ("B07", "A batch above the SO row's outstanding (within the PO row's free quantity) is refused with no PUT", "b07"),
    ("B08", "Create resend: the POST landed, the answer was lost; the resend finds the document (<<New>> body)", "b08"),
    ("B09", "Create resend: nothing was sent; the resend finds nothing and POSTs once (<<New>> body)", "b09"),
    ("B10", "Create resend: the POST landed, the answer was lost; the resend finds the document (numbered body)", "b10"),
    ("B11", "Mixed batch: two good lines and one above the SO row's outstanding; the two link, the third is skipped", "b11"),
)
_B_PRICE = 1.0
_B_SO_LOCATION = "HQ"  # the unlink merge needs the batch rows and the free row at one location (D7)


class _FaultClient:
    """Wraps the tapped client: when the run's ``fault`` is armed, the next POST either lands and then
    times out ("after": the answer is lost) or times out before anything is sent ("before")."""

    def __init__(self, inner, run) -> None:
        self._inner, self._run = inner, run

    def attach_call_log(self, log: cl.CallLog) -> None:
        self._inner.attach_call_log(log)

    def post(self, path: str, body: object):
        mode, self._run.fault = self._run.fault, None
        if mode == "before":
            raise WriteTransportError("WRITE_TIMEOUT")
        response = self._inner.post(path, body)
        if mode == "after":
            raise WriteTransportError("WRITE_TIMEOUT")
        return response

    def put(self, path: str, body: object):
        return self._inner.put(path, body)

    def delete(self, path: str, body: object):
        return self._inner.delete(path, body)

    def delete_query(self, path: str, params: Dict[str, str]):
        return self._inner.delete_query(path, params)


class _BatchRun:
    """The batch suite: documents created through the real create primitive, links and unlinks through
    ``OperationService.run`` (the code the gateway runs), every vendor request tapped and call-logged."""

    def __init__(self, db: Session, tenant_id: str, company: AcCompany, base_url: str, creditor: str,
                 debtor: str, run_tag: str, client_factory, reader_factory, sink_factory) -> None:
        self.db, self.tenant_id, self.company, self.base_url = db, tenant_id, company, base_url
        self.creditor, self.debtor, self.tag = creditor, debtor, run_tag
        self.tap = _Tap()
        self.fault: Optional[str] = None
        wrapped_client = lambda url: _FaultClient(_TapClient(client_factory(url), self.tap), self)  # noqa: E731
        wrapped_reader = lambda url: _TapReader(reader_factory(url), self.tap)  # noqa: E731
        self.prims = PrimitiveService(db, client_factory=wrapped_client, reader_factory=wrapped_reader,
                                      sink_factory=sink_factory, actor=cl.ACTOR_RUNNER)
        self.ops = OperationService(db, client_factory=wrapped_client, reader_factory=wrapped_reader,
                                    sink_factory=sink_factory, actor=cl.ACTOR_RUNNER)
        self.today = myt_date(datetime.now(timezone.utc))
        self.evidence: List[Dict[str, object]] = []
        self.timings: List[Dict[str, object]] = []
        self.case_id = ""
        self.so: Dict[str, PrimitiveResult] = {}
        self.po: Optional[PrimitiveResult] = None
        self.keys: Dict[str, int] = {}  # PO row name -> DtlKey
        self.batch_rows: Dict[str, int] = {}  # B03 SO line name -> new PO DtlKey
        self.po_no = f"{_doc_prefix(run_tag)}-PO"

    # ── helpers ──────────────────────────────────────────────────────────────

    def _args(self, kind: str) -> Dict[str, object]:
        return {"tenant_id": self.tenant_id, "company_id": self.company.id, "kind": kind}

    def _day(self) -> str:
        return f"{self.today.isoformat()}T00:00:00"

    def _row(self, qty: float, location: str, **over: object) -> Dict[str, object]:
        row: Dict[str, object] = dict(_Q_ITEM, Qty=qty, UnitPrice=_B_PRICE, Location=location, DeliveryDate=self._day())
        row.update(over)
        return row

    def _header(self, **over: object) -> Dict[str, object]:
        head: Dict[str, object] = {"DocDate": self._day(), "DisplayTerm": "C.B.D.", "CurrencyCode": "MYR",
                                   "CurrencyRate": 1.0}
        head.update(over)
        return head

    def _read(self, kind: str, doc_key: int) -> Dict[str, object]:
        res = self.prims.read_doc(**self._args(kind), doc_key=doc_key, doc_date=self.today)
        return res.document or {}

    def _rows(self, doc: Dict[str, object]) -> List[Dict[str, object]]:
        return list(doc.get("Details") or [])  # type: ignore[call-overload]

    def _po_row(self, doc: Dict[str, object], key: int) -> Optional[Dict[str, object]]:
        return next((r for r in self._rows(doc) if r.get("DtlKey") == key), None)

    def _record(self, case: CaseResult, first_write: int) -> None:
        for entry in self.tap.writes[first_write:]:
            self.evidence.append({
                "case": case.case_id, "method": entry["method"], "path": entry["path"],
                "requestBody": entry["requestBody"], "responseStatus": entry["responseStatus"],
                "responseBody": entry["responseBody"],
            })
            status = entry["responseStatus"]
            answer = _scrub(entry["responseBody"]) if isinstance(status, int) and 200 <= status < 300 else (
                vendor_message(entry["responseBody"], self.base_url) or f"status {status}")
            case.steps.append(Step(str(entry["method"]), str(entry["path"]), status,  # type: ignore[arg-type]
                                   _scrub(entry["requestBody"]), response=answer))  # type: ignore[arg-type]

    def _posts_since(self, since: datetime) -> int:
        from sqlalchemy import func as sa_func
        from modules.autocount.models import AcApiCallLog

        self.db.rollback()
        return int(self.db.query(sa_func.count(AcApiCallLog.id)).filter(
            AcApiCallLog.tenant_id == self.tenant_id, AcApiCallLog.company_id == self.company.id,
            AcApiCallLog.actor == cl.ACTOR_RUNNER, AcApiCallLog.created_at >= since,
            AcApiCallLog.method == "POST").scalar() or 0)

    def _call_log_counts(self, since: datetime) -> "tuple[int, int]":
        """``(rows, PUT rows)`` this company's runner calls added to ``ac_api_call_log`` since ``since``."""
        from sqlalchemy import func as sa_func
        from modules.autocount.models import AcApiCallLog

        self.db.rollback()
        base = self.db.query(sa_func.count(AcApiCallLog.id)).filter(
            AcApiCallLog.tenant_id == self.tenant_id, AcApiCallLog.company_id == self.company.id,
            AcApiCallLog.actor == cl.ACTOR_RUNNER, AcApiCallLog.created_at >= since,
        )
        return int(base.scalar() or 0), int(base.filter(AcApiCallLog.method == "PUT").scalar() or 0)

    def _timed(self, case: CaseResult, label: str, n: int, fn):
        """Run ``fn`` (one or more operations), keep wall time, PUT count and call-log rows."""
        import time

        start_write, since = len(self.tap.writes), datetime.now(timezone.utc)
        t0 = time.monotonic()
        out = fn()
        ms = int((time.monotonic() - t0) * 1000)
        self._record(case, start_write)
        rows, puts = self._call_log_counts(since)
        self.timings.append({"case": case.case_id, "label": label, "lines": n, "ms": ms, "puts": puts, "logRows": rows})
        case.http_calls = len(self.tap.writes) - start_write
        return out

    def _run_op(self, op: str, key: str, params: Dict[str, object]):
        return self.ops.run(tenant_id=self.tenant_id, company_id=self.company.id, key_id=None,
                            idempotency_key=f"{self.tag}-{key}", op=op, params=params)

    # ── cases ────────────────────────────────────────────────────────────────

    def b00(self, case: CaseResult) -> None:
        case.expected = "SO1 (3 rows qty 10), SO2 (2 rows qty 10), SO3 (1 row qty 5), PO with rows A10 B12 C10 D6 E4"
        prefix = _doc_prefix(self.tag)
        start = len(self.tap.writes)
        for name, qtys in (("SO1", (10, 10, 10)), ("SO2", (10, 10)), ("SO3", (5,))):
            res = self.prims.create_doc(
                **self._args("SO"), header=self._header(DebtorCode=self.debtor, DocNo=f"{prefix}-{name}"),
                lines=[self._row(q, _B_SO_LOCATION) for q in qtys])
            if res.outcome != "done":
                case.observed = f"{name} {res.outcome} {res.error_code or ''}".strip()
                self._record(case, start)
                return
            self.so[name] = res
        po = self.prims.create_doc(
            **self._args("PO"), header=self._header(CreditorCode=self.creditor, DocNo=self.po_no),
            lines=[self._row(q, "HQ") for q in (10, 12, 10, 6, 4)])
        self._record(case, start)
        if po.outcome != "done":
            case.observed = f"PO {po.outcome} {po.error_code or ''}".strip()
            return
        self.po = po
        for name, row in zip("ABCDE", self._rows(po.document or {})):
            self.keys[name] = int(row["DtlKey"])  # type: ignore[call-overload]
        case.status = PASS
        case.observed = f"created {', '.join(f'{k} {v.doc_no}' for k, v in self.so.items())} and {po.doc_no}"

    def _so_row(self, name: str, index: int) -> int:
        return int(self._rows(self.so[name].document or {})[index]["DtlKey"])  # type: ignore[call-overload]

    def _link(self, name: str, index: int, qty: object) -> Dict[str, object]:
        return {"so_doc_key": int(self.so[name].doc_key or 0), "so_dtl_key": self._so_row(name, index), "qty": qty}

    def _batch(self, case: CaseResult, row: str, links: List[Dict[str, object]], key: str, label: str) -> bool:
        if self.po is None or any(n not in self.so for n in ("SO1", "SO2", "SO3")):
            case.status, case.observed = SKIPPED, "B00 did not pass"
            return False
        params = {"doc_key": int(self.po.doc_key or 0), "dtl_key": self.keys[row], "links": links,
                  "doc_date": self.today}
        res = self._timed(case, label, len(links), lambda: self._run_op("link_batch", key, params))
        doc = self._read("PO", int(self.po.doc_key or 0))
        ok = res.outcome == "done" and res.batch is not None
        notes = [f"{res.outcome}" + (f" {res.error_code}" if res.error_code else "")]
        if ok:
            answer = {a["soDtlKey"]: a for a in res.batch["links"]}  # type: ignore[index]
            taken = Decimal(0)
            for link in links:
                got = self._po_row(doc, int(answer[link["so_dtl_key"]]["poDtlKey"])) if link["so_dtl_key"] in answer else None
                taken += _num(link["qty"])
                good = (got is not None and got.get("FromSODtlKey") == link["so_dtl_key"]
                        and _num(got.get("Qty")) == _num(link["qty"]) and got.get("Location") == _B_SO_LOCATION
                        and _num(got.get("UnitPrice")) == Decimal(str(_B_PRICE))
                        and str(got.get("DeliveryDate") or "")[:10] == self.today.isoformat())
                ok = ok and good
            free = res.batch.get("freeLine")  # type: ignore[union-attr]
            want_free = _num(self.qtys[row]) - taken
            ok = ok and ((free is None and want_free == 0) or (free is not None and _num(free["qty"]) == want_free))
            notes.append(f"{len(answer)} linked rows, free line {free['qty'] if free else 'none'}, warnings {','.join(res.warnings) or 'none'}")
            for link in links:
                self.batch_rows[f"{link['so_dtl_key']}:{row}"] = int(answer[link["so_dtl_key"]]["poDtlKey"])
        case.observed = "; ".join(notes) + f"; {self.timings[-1]['ms']} ms, {self.timings[-1]['puts']} PUT"
        case.status = PASS if ok else FAIL
        return ok

    qtys = {"A": 10, "B": 12, "C": 10, "D": 6, "E": 4}

    def b01(self, case: CaseResult) -> None:
        case.expected = "one PUT 1 (+ at most one PUT 2), 1 linked row at the SO row's location, price and date kept, free row 7"
        self._batch(case, "A", [self._link("SO1", 0, 3)], "b01", "batch of 1")

    def b02(self, case: CaseResult) -> None:
        case.expected = "one PUT 1 (+ at most one PUT 2), 3 linked rows, the row deleted (sum equals its quantity)"
        self._batch(case, "B", [self._link("SO1", 1, 4), self._link("SO1", 2, 4), self._link("SO2", 0, 4)],
                    "b02", "batch of 3")

    def b03(self, case: CaseResult) -> None:
        case.expected = "one PUT 1 (+ at most one PUT 2), 5 linked rows, free row 5"
        self._batch(case, "C", [self._link("SO1", 0, 1), self._link("SO1", 1, 1), self._link("SO1", 2, 1),
                                self._link("SO2", 0, 1), self._link("SO2", 1, 1)], "b03", "batch of 5")

    def b04(self, case: CaseResult) -> None:
        case.expected = "three link_row calls, each its own split (PUT 1 + restore PUT)"
        if self.po is None or "SO1" not in self.so:
            case.status, case.observed = SKIPPED, "B00 did not pass"
            return
        calls = [("SO1", 0), ("SO1", 1), ("SO2", 1)]

        def go():
            outs = []
            for i, (name, idx) in enumerate(calls):
                outs.append(self._run_op("link_row", f"b04-{i}", {
                    "doc_key": int(self.po.doc_key or 0), "dtl_key": self.keys["D"],  # type: ignore[union-attr]
                    "so_doc_key": int(self.so[name].doc_key or 0), "so_dtl_key": self._so_row(name, idx),
                    "qty": 1, "doc_date": self.today}))
            return outs

        outs = self._timed(case, "today: 3 calls", 3, go)
        case.observed = ", ".join(o.outcome + (f" {o.error_code}" if o.error_code else "") for o in outs) + (
            f"; {self.timings[-1]['ms']} ms, {self.timings[-1]['puts']} PUT")
        case.status = PASS if all(o.outcome == "done" for o in outs) else FAIL

    def b05(self, case: CaseResult) -> None:
        case.expected = ("unlink of a B03 batch row: ONE PUT, the row deleted, the FIRST matching free row (the B01 free "
                         "row, row order) raised by its quantity, the answer names it")
        key = self.batch_rows.get(f"{self._so_row('SO1', 0)}:C") if "SO1" in self.so else None
        if key is None or self.po is None:
            case.status, case.observed = SKIPPED, "B03 did not pass"
            return
        before = self._po_row(self._read("PO", int(self.po.doc_key or 0)), self.keys["A"])
        res = self._timed(case, "unlink merge", 1, lambda: self._run_op("unlink_row", "b05", {
            "doc_key": int(self.po.doc_key or 0), "dtl_key": key, "doc_date": self.today}))  # type: ignore[union-attr]
        doc = self._read("PO", int(self.po.doc_key or 0))
        free = self._po_row(doc, self.keys["A"])
        ok = (res.outcome == "done" and res.replaced_lines == [(key, self.keys["A"])]
              and free is not None and before is not None and self._po_row(doc, key) is None
              and _num(free.get("Qty")) == _num(before.get("Qty")) + 1 and self.timings[-1]["puts"] == 1)
        case.observed = (f"{res.outcome}, replaced {res.replaced_lines}, free row {free.get('Qty') if free else 'gone'}, "
                         f"{self.timings[-1]['ms']} ms, {self.timings[-1]['puts']} PUT")
        case.status = PASS if ok else FAIL

    def b06(self, case: CaseResult) -> None:
        case.expected = ("a batch with one quantity above the SO row's outstanding is refused before any PUT; the "
                         "body fixed and the SAME key resent runs fresh and is done (plan 62 D6)")
        if self.po is None or "SO2" not in self.so:
            case.status, case.observed = SKIPPED, "B00 did not pass"
            return
        bad = [self._link("SO2", 1, 100)]
        good = [self._link("SO2", 1, 1)]
        base = {"doc_key": int(self.po.doc_key or 0), "dtl_key": self.keys["E"], "doc_date": self.today}
        first = self._timed(case, "retry: refused batch", 1, lambda: self._run_op("link_batch", "b06", dict(base, links=bad)))
        puts_first = self.timings[-1]["puts"]
        second = self._timed(case, "retry: fixed batch, same key", 1,
                             lambda: self._run_op("link_batch", "b06", dict(base, links=good)))
        case.observed = (f"first {first.outcome} {first.error_code or ''} ({puts_first} PUT); resend with the same key "
                         f"{second.outcome} {second.error_code or ''}").strip()
        case.status = PASS if first.outcome == "refused" and puts_first == 0 and second.outcome == "done" else FAIL


    def b07(self, case: CaseResult) -> None:
        case.expected = ("a batch whose only line is within the PO row's free quantity but above the SO row's "
                         "outstanding: every line skipped, refused ALL_LINKS_SKIPPED naming QTY_ABOVE_OUTSTANDING, 0 PUTs")
        if self.po is None or "SO2" not in self.so:
            case.status, case.observed = SKIPPED, "B00 did not pass"
            return
        doc = self._read("PO", int(self.po.doc_key or 0))
        so_key = self._so_row("SO2", 1)
        linked = sum((_num(r.get("Qty")) for r in self._rows(doc) if r.get("FromSODtlKey") == so_key), Decimal(0))
        outstanding = Decimal(10) - linked
        free = _num((self._po_row(doc, self.keys["A"]) or {}).get("Qty"))
        qty = outstanding + 1
        if qty > free:
            case.observed = f"setup: free row {free} cannot carry {qty}"
            return
        link = {"so_doc_key": int(self.so["SO2"].doc_key or 0), "so_dtl_key": so_key, "qty": qty}
        params = {"doc_key": int(self.po.doc_key or 0), "dtl_key": self.keys["A"], "links": [link], "doc_date": self.today}
        res = self._timed(case, "refused above outstanding", 1, lambda: self._run_op("link_batch", "b07", params))
        puts = self.timings[-1]["puts"]
        skipped = (res.batch or {}).get("skipped") or []
        codes = [(x["soDtlKey"], x["code"]) for x in skipped]
        case.observed = (f"{res.outcome} {res.error_code or ''}, skipped {codes} (qty {qty}, outstanding {outstanding}, "
                         f"free {free}, {puts} PUT)").strip()
        case.status = PASS if (res.outcome == "refused" and res.error_code == "ALL_LINKS_SKIPPED" and puts == 0
                               and codes == [(so_key, "QTY_ABOVE_OUTSTANDING")]) else FAIL

    def b11(self, case: CaseResult) -> None:
        case.expected = ("owner rule: one bad line never fails the batch. Two good lines and one above the SO row's "
                         "outstanding: done, 2 linked rows, the third named in skipped with QTY_ABOVE_OUTSTANDING, "
                         "2 PUTs (PUT 1 with the two lines, one restore PUT)")
        if self.po is None or "SO3" not in self.so or "SO2" not in self.so:
            case.status, case.observed = SKIPPED, "B00 did not pass"
            return
        doc = self._read("PO", int(self.po.doc_key or 0))
        so3 = self._so_row("SO3", 0)
        linked3 = sum((_num(r.get("Qty")) for r in self._rows(doc) if r.get("FromSODtlKey") == so3), Decimal(0))
        bad_qty = Decimal(5) - linked3 + 1
        links = [self._link("SO2", 0, 1), self._link("SO2", 1, 1), self._link("SO3", 0, bad_qty)]
        params = {"doc_key": int(self.po.doc_key or 0), "dtl_key": self.keys["A"], "links": links, "doc_date": self.today}
        res = self._timed(case, "mixed batch (2 good, 1 skipped)", 3, lambda: self._run_op("link_batch", "b11", params))
        puts = self.timings[-1]["puts"]
        batch = res.batch or {}
        codes = [(x["soDtlKey"], x["code"]) for x in batch.get("skipped") or []]
        case.observed = (f"{res.outcome} {res.error_code or ''}, {len(batch.get('links') or [])} linked, skipped {codes}, "
                         f"{puts} PUT").strip()
        case.status = PASS if (res.outcome == "done" and len(batch.get("links") or []) == 2 and puts == 2
                               and codes == [(so3, "QTY_ABOVE_OUTSTANDING")]) else FAIL

    def _create_case(self, case: CaseResult, key: str, fault: str, number: Optional[str], qty: int) -> None:
        """A QT create through ``run_primitive`` with an armed fault, then the SAME key resent."""
        header: Dict[str, object] = {"docNo": number} if number else {}
        header["debtorCode"] = self.debtor
        params = {"header": header, "lines": [{"itemCode": _Q_ITEM["ItemCode"], "qty": qty, "uom": _Q_ITEM["UOM"]}]}
        vendor_header = self._header(DebtorCode=self.debtor, **({"DocNo": number} if number else {}))
        lines = [self._row(qty, "HQ")]

        def send():
            return self.ops.run_primitive(
                tenant_id=self.tenant_id, company_id=self.company.id, key_id=None,
                idempotency_key=f"{self.tag}-{key}", name="create_doc", kind="QT", doc_key=None, params=params,
                call=lambda: self.prims.create_doc(**self._args("QT"), header=vendor_header, lines=lines))

        since = datetime.now(timezone.utc)
        start = len(self.tap.writes)
        self.fault = fault
        first = send()
        second = send()
        third = send()  # the key is settled now: a further resend changes nothing
        self._record(case, start)
        posts = self._posts_since(since)
        found = second.get("outcome") == "done" and second.get("docNo")
        landed = fault == "after"
        ok = (first.get("outcome") == "pending_verification" and second.get("outcome") == "done" and bool(found)
              and third.get("docNo") == second.get("docNo") and posts == 1)
        if landed:
            try:  # the document the resend named is the one AutoCount saved
                ok = ok and self.prims._reader_for(self.base_url).get_by_doc_no("QT", str(found)).get("DocNo") == found
            except DocReadError:
                ok = False
        case.observed = (f"first {first.get('outcome')} {first.get('errorCode') or ''}; resend {second.get('outcome')} "
                         f"{second.get('docNo') or ''}; {posts} POST in ac_api_call_log").strip()
        case.status = PASS if ok else FAIL

    def b08(self, case: CaseResult) -> None:
        case.expected = ("the POST lands, then times out; the resend of the SAME key looks the document up "
                         "(<<New>> body: day list, debtor, time window, lines), answers done with its DocNo, 0 second POST")
        self._create_case(case, "b08", "after", None, 3)

    def b09(self, case: CaseResult) -> None:
        case.expected = ("the call times out before anything is sent; the resend finds no document, releases the "
                         "key and POSTs once: 1 POST in total")
        self._create_case(case, "b09", "before", None, 4)

    def b10(self, case: CaseResult) -> None:
        case.expected = ("numbered body: the POST lands, then times out; the resend finds the document by DocNo, "
                         "answers done, 0 second POST")
        self._create_case(case, "b10", "after", f"{_doc_prefix(self.tag)}-QTN", 5)


def _timing_table(rows: List[Dict[str, object]]) -> str:
    out = ["## Timings", "", "| Case | Calls | SO lines | Wall ms | PUTs | ac_api_call_log rows |", "|---|---|---|---|---|---|"]
    for r in rows:
        calls = 3 if str(r["label"]).startswith("today") else 1
        out.append(f"| {r['case']} {r['label']} | {calls} | {r['lines']} | {r['ms']} | {r['puts']} | {r['logRows']} |")
    return "\n".join(out)


def run_batch_suite(
    db: Session,
    *,
    tenant_id: str,
    company_id: str,
    creditor_code: str,
    debtor_code: str,
    run_tag: str,
    client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
    reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
    sink_factory: Optional[Callable[..., object]] = None,
) -> SuiteResult:
    """Run B00..B06 (plan 62) through the real ``OperationService``. Same guards as the other suites:
    a test book (in every environment) and a test company, all BEFORE any request."""
    from modules.autocount.write_back.pull_docs import WriteDisabled

    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        raise WriteDisabled()
    base_url = write_base_url(db, company)
    _require_test_book(base_url)
    write_auth_headers(db, company)  # an unusable API key setting refuses the run before any request
    guard.assert_test_company(db, tenant_id, company.id, book=guard.book_of(base_url))
    run = _BatchRun(db, tenant_id, company, base_url, creditor_code, debtor_code, run_tag,
                    client_factory or AutoCountWriteClient, reader_factory or AutoCountDocReader, sink_factory)
    suite = SuiteResult(run_tag=run_tag)
    for case_id, title, method in _B_CASES:
        case = CaseResult(case_id, title)
        run.case_id = case_id
        try:
            getattr(run, method)(case)
        except Exception as exc:  # noqa: BLE001 - one case never stops the suite
            logger.exception("write-back runner case %s failed", case_id)
            case.status = FAIL
            case.observed = f"{case.observed} {type(exc).__name__}".strip()
        db.rollback()
        suite.cases.append(case)
    suite.evidence = run.evidence
    suite.summary = _timing_table(run.timings)
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
    parser.add_argument("--suite", choices=("db3", "qtso", "batch"), default="db3")
    parser.add_argument("--evidence", help="qtso: path of the exact (private) evidence JSON")
    parser.add_argument("--header-extra", help="qtso: JSON file of header fields (names, addresses) to send")
    args = parser.parse_args(argv)
    if args.suite in ("db3", "batch") and not args.creditor:
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
            elif args.suite == "batch":
                result = run_batch_suite(
                    db, tenant_id=tenant.id, company_id=args.company_id, creditor_code=args.creditor,
                    debtor_code=args.debtor, run_tag=args.run_tag,
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

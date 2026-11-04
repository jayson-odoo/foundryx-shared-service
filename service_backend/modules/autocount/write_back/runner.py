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
    PO_BY_DOC_DATE_PATH,
)
from modules.autocount.write_back.guard import WriteNotAllowed
from modules.autocount.write_back.payloads import header_of
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
TEST_SPLIT_SO_ROW = 11989  # SRTKT38SS qty 10 @BRW-AM
TEST_MOVE_SO_ROW = 11992  # SRTKT38SS qty 10 @BRW-AM
BASELINE_FROM = date(2026, 1, 26)  # SO389293 DocDate
BASELINE_TO = date(2026, 2, 4)  # PO 202602-S0007 DocDate
STALE_STAMP = "1900-01-01T00:00:00.00"
ITEM = "SRTKT38SS"

# Header fields kept as evidence of a create: codes and numbers only, never names.
_EVIDENCE_HEADER = ("DocNo", "DocDate", "CreditorCode", "ShippingPO")
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


@dataclass
class CaseResult:
    case_id: str
    title: str
    status: str = FAIL
    expected: str = ""
    observed: str = ""
    steps: List[Step] = field(default_factory=list)
    action_id: Optional[str] = None


@dataclass
class SuiteResult:
    run_tag: str
    cases: List[CaseResult] = field(default_factory=list)


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
        self.tag = run_tag
        self.client_factory = client_factory
        self.reader_factory = reader_factory
        self.sink_factory = sink_factory
        self.service = WriteBackService(
            db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory,
        )
        self.today = myt_date(datetime.now(timezone.utc))
        self.po_no = f"FXT-{run_tag}-1"
        self.spo_no = f"FXT-{run_tag}-S1"
        self.results: Dict[str, CaseResult] = {}
        self.po_doc: Optional[Doc] = None
        self.split_key: Optional[int] = None
        self.spo_doc: Optional[Doc] = None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _pull(self, d_from: date, d_to: date) -> PullDocsResult:
        return pull_documents(
            self.db, tenant_id=self.tenant_id, company_id=self.company.id,
            date_from=d_from, date_to=d_to, mode=MODE_DOC_DATE,
            reader_factory=self.reader_factory, sink_factory=self.sink_factory,
        )

    def _find_doc(self, doc_no: str) -> Optional[Doc]:
        self.db.commit()  # no transaction open during a GET
        reader = self.reader_factory(self.base_url)
        for doc in reader.list_day("PO", self.today, by_last_modified=False):
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

    def _put_step(self, row: Optional[AcWriteAction]) -> List[Step]:
        if row is None or not row.request_json:
            return []
        body: Doc = row.request_json  # type: ignore[assignment]
        sent = body.get("Details") or []
        touched = {r.get("DtlKey") for r in sent if r.get("DtlKey")}
        before = (row.before_json or {}).get("Details") or []
        after = (row.after_json or {}).get("Details") or []
        before_keys = {r.get("DtlKey") for r in before}
        return [Step(
            "PUT", EDIT_PO_PATH, row.response_status,
            {"DocKey": body.get("DocKey"), "DocNo": body.get("DocNo"), "Details": _rows(sent)},
            _rows([r for r in before if r.get("DtlKey") in touched]),
            _rows([r for r in after if r.get("DtlKey") in touched or r.get("DtlKey") not in before_keys]),
        )]

    def _service_case(
        self, case: CaseResult, result: WriteActionResult, outcome: str, code: Optional[str] = None
    ) -> bool:
        """Record a service answer on the case; True when it is the expected one."""
        row = self._action(result)
        case.steps.extend(self._put_step(row))
        case.action_id = result.action_id
        case.observed = result.outcome + (f" {result.error_code}" if result.error_code else "")
        return result.outcome == outcome and (code is None or result.error_code == code)

    def _setup_post(self, case: CaseResult, body: Doc, doc_no: str) -> Optional[Doc]:
        """Check the DocNo is absent today, POST the document, read it back by DocNo."""
        existing = self._find_doc(doc_no)
        case.steps.append(Step("GET", PO_BY_DOC_DATE_PATH, 200, note=f"{doc_no} absent" if existing is None else f"{doc_no} present"))
        if existing is not None:
            case.observed = f"{doc_no} already exists for today; pick another run tag"
            return None
        self.db.commit()
        try:
            response = self.client_factory(self.base_url).post(NEW_PO_PATH, body)
        except WriteTransportError as exc:
            case.observed = f"create failed {exc.code}"
            return None
        sent = {k: body[k] for k in _EVIDENCE_HEADER if k in body}
        sent["Details"] = _rows(body["Details"])  # type: ignore[arg-type]
        case.steps.append(Step("POST", NEW_PO_PATH, response.status_code, sent))
        if not response.ok:
            case.observed = f"create refused by the vendor, status {response.status_code}"
            return None
        doc = self._find_doc(doc_no)
        if doc is None:
            case.observed = f"{doc_no} not found after create"
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
        if self._skip(case, "C01"):
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

    def c03(self, case: CaseResult) -> None:
        case.expected = "split: 40 stay at HQ, a new 10 row at BRW-AM linked to SO row 11989"
        if self._skip(case, "C02"):
            return
        big = next(r for r in self._test_rows() if _num(r.get("Qty")) == 50)
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(big["DtlKey"]),  # type: ignore[index,arg-type]
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=TEST_SPLIT_SO_ROW, qty=Decimal(10),
        )
        if self._service_case(case, result, "done"):
            rows = (result.document or {}).get("Details") or []
            split = [r for r in rows if r.get("FromSODtlKey") == TEST_SPLIT_SO_ROW]
            if len(split) == 1:
                self.split_key = int(split[0]["DtlKey"])  # type: ignore[arg-type]
                self.po_doc = result.document
                case.status = PASS

    def c04(self, case: CaseResult) -> None:
        case.expected = "same quantity: the row moves to BRW-AM in place, no row added"
        if self._skip(case, "C03"):
            return
        small = next(r for r in self._test_rows() if _num(r.get("Qty")) == 10 and not r.get("FromSODtlKey"))
        before_count = len(self._test_rows())
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=int(small["DtlKey"]),  # type: ignore[index,arg-type]
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=TEST_MOVE_SO_ROW, qty=Decimal(10),
        )
        if self._service_case(case, result, "done") and len((result.document or {}).get("Details") or []) == before_count:  # type: ignore[arg-type]
            self.po_doc = result.document
            case.status = PASS

    def _refusal(self, case: CaseResult, code: str, **link: object) -> None:
        result = self.service.link(tenant_id=self.tenant_id, company_id=self.company.id, **link)  # type: ignore[arg-type]
        if self._service_case(case, result, "refused", code):
            case.status = PASS

    def c05(self, case: CaseResult) -> None:
        case.expected = "link refused: the SO row is fully covered (QTY_ABOVE_OUTSTANDING)"
        self._refusal(
            case, "QTY_ABOVE_OUTSTANDING", po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=FREE_PO_ROW,
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=COVERED_SO_ROW, qty=Decimal(1),
        )

    def c06(self, case: CaseResult) -> None:
        case.expected = "link refused: quantity above the PO row (QTY_ABOVE_FREE)"
        self._refusal(
            case, "QTY_ABOVE_FREE", po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=FREE_PO_ROW,
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=SO_ROW_QTY_2_SIDE, qty=Decimal(2),
        )

    def c07(self, case: CaseResult) -> None:
        case.expected = "unlink of the linked real row 12013 is done"
        result = self.service.unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=LINKED_PO_ROW,
        )
        if self._service_case(case, result, "done"):
            case.status = PASS

    def c08(self, case: CaseResult) -> None:
        case.expected = "relink of row 12013 to SO row 11993 is done and reads back linked"
        if self._skip(case, "C07"):
            return
        result = self.service.link(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=REAL_PO_DOC_KEY, po_dtl_key=LINKED_PO_ROW,
            so_doc_key=REAL_SO_DOC_KEY, so_dtl_key=LINKED_SO_ROW, qty=Decimal(10),
        )
        rows = (result.document or {}).get("Details") or []
        linked = any(r.get("DtlKey") == LINKED_PO_ROW and r.get("FromSODtlKey") == LINKED_SO_ROW for r in rows)
        if self._service_case(case, result, "done") and linked:
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
        case.expected = "SPO created pointing at the split row; unlinking that PO row is refused (ROW_ON_SPO)"
        if self._skip(case, "C03"):
            return
        if self.split_key is None:
            case.observed = "C03 left no split row"
            return
        body = self._create_body(
            case, self.spo_no,
            [{"ItemCode": ITEM, "Qty": 10, "Location": "BRW-AM", "FromDocType": "PO",
              "FromDocNo": self.po_no, "FromDocDtlKey": self.split_key}],
            spo=True,
        )
        if body is None:
            return
        doc = self._setup_post(case, body, self.spo_no)
        if doc is None:
            return
        if doc.get("ShippingPO") != "T":
            case.observed = "the vendor did not honour ShippingPO T: the document reads back as a plain PO"
            return
        self.spo_doc = doc
        pulled = self._pull(self.today, self.today)  # stages the SPO
        if pulled.failed:
            case.observed = f"pull failed {pulled.error_code}"
            return
        result = self.service.unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=self.split_key,  # type: ignore[index,arg-type]
        )
        if self._service_case(case, result, "refused", "ROW_ON_SPO"):
            case.status = PASS

    def c11(self, case: CaseResult) -> None:
        case.expected = "SPO row unlinked, then the PO row unlinked, both done"
        if self._skip(case, "C10"):
            return
        spo_row = (self.spo_doc.get("Details") or [])[0]  # type: ignore[index]
        first = self.service.spo_unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            spo_doc_key=int(self.spo_doc["DocKey"]), spo_dtl_key=int(spo_row["DtlKey"]),  # type: ignore[arg-type]
        )
        if not self._service_case(case, first, "done"):
            return
        second = self.service.unlink(
            tenant_id=self.tenant_id, company_id=self.company.id,
            po_doc_key=int(self.po_doc["DocKey"]), po_dtl_key=self.split_key,  # type: ignore[index,arg-type]
        )
        first_observed = case.observed
        if self._service_case(case, second, "done"):
            case.observed = f"spo_unlink {first_observed}; unlink {case.observed}"
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
    ("C01", "Create the test PO", "c01"),
    ("C02", "Pull SO then PO into staging", "c02"),
    ("C03", "Link with split", "c03"),
    ("C04", "Link same quantity, location moves", "c04"),
    ("C05", "Over-link refused", "c05"),
    ("C06", "Quantity above the PO row refused", "c06"),
    ("C07", "Unlink a linked real row", "c07"),
    ("C08", "Relink the real row", "c08"),
    ("C09", "Stale document refused", "c09"),
    ("C10", "SPO precondition", "c10"),
    ("C11", "SPO unlink then PO unlink", "c11"),
    ("C12", "Other book refused with no request", "c12"),
)


def run_db3_suite(
    db: Session,
    *,
    tenant_id: str,
    company_id: str,
    creditor_code: str,
    run_tag: str,
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
    run = _Run(
        db, tenant_id, company, base_url, creditor_code, run_tag,
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the db3 write-back suite.")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--creditor", required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from app.models.tenant import Tenant

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print("error: unknown tenant")
            return 2
        try:
            result = run_db3_suite(
                db, tenant_id=tenant.id, company_id=args.company_id,
                creditor_code=args.creditor, run_tag=args.run_tag,
            )
        except (WriteNotAllowed, Exception) as exc:  # noqa: BLE001
            print(f"error: {getattr(exc, 'code', type(exc).__name__)}")
            return 2
    today = myt_date(datetime.now(timezone.utc))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render_report(result, run_date=today))
    for case in result.cases:
        print(f"{case.case_id} {case.status}")
    return 0 if all(c.status != FAIL for c in result.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())

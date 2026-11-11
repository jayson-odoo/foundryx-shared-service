"""Plan 57 test helper: an in-memory fake AutoCount hapi wrapper (no network).

``FakeAutoCountVendor`` holds QT / SO / PO / SPO documents and serves them behind
an ``httpx.MockTransport``. It honours the behaviour recorded on db3 on 4 Nov 2026:

* POST /New<Doc>: answer text ``DocNo=<no> ,DocKey=<key> ... Created Successful.``;
  ``"<<New>>"`` takes the next number; a missing DocNo or a header without
  DisplayTerm answers 500.
* PUT /Edit<Doc>bydockey: ``... Done Edit.``; ``DtlKey 0`` adds a row; rows the body
  omits are kept; Qty 0 is stored; header ``Cancelled`` is ignored; link fields on
  an EXISTING row are ignored; a NEW row linked to an SO row is forced to Location
  HQ and an SO link reads back as ``FromSODtlKey`` on PO rows.
* GET /<doc>bydocdate?DocDate=YYYYMMDD.
* GET /debtorbypage?page=&pageSize= - the paged envelope over ``debtors``
  (SS-QTSO-DISPLAYTERM: the debtor's own ``DisplayTerm``).
* Plan 61 (db3 probes, 10 Nov 2026): GET ``/<Doc>bydocno?DocNo=`` (list, ``[]`` when
  unknown); DELETE ``/Cancel<Doc>bydocno?DocNo=`` (no body; 200 and ``Cancelled "T"`` /
  ``DocStatus "V"``; 400 when void, transferred onward or unknown); a PUT row with
  ``FullTransferOption "D"`` deletes that DtlKey (refused 500 when the row was transferred
  onward); a PUT is ALL OR NOTHING (a refused row changes nothing); a NEW PO row linked to
  an SO row is forced to ``Location HQ`` / ``DeliveryDate 0001-01-01`` and reads its link as
  ``FromSODtlKey`` (``FromDocType`` reads ``""``); an edit of a void document answers 500.
  The old placeholder DELETE doors do not exist (404).

Failure injection (each consumed by exactly one call): ``fail_next``,
``timeout_next``, ``apply_then_500_next``, ``drop_rows_next_create``. Every request
lands on ``calls``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import httpx

# kind -> (wrapper noun, GET path leaf, party field, store, number prefix)
SPECS: Dict[str, Dict[str, str]] = {
    "QT": {"noun": "Quotation", "get": "quotationbydocdate", "party": "DebtorCode", "store": "QT", "prefix": "QT"},
    "SO": {"noun": "SalesOrder", "get": "salesorderbydocdate", "party": "DebtorCode", "store": "SO", "prefix": "SO"},
    "PO": {"noun": "PurchaseOrder", "get": "purchaseorderbydocdate", "party": "CreditorCode", "store": "PO", "prefix": "PO"},
    "SPO": {"noun": "PurchaseOrder", "get": "purchaseorderbydocdate", "party": "CreditorCode", "store": "PO", "prefix": "SPO"},
}
LINK_FIELDS = ("FromDocType", "FromDocNo", "FromDocDtlKey", "FromSODtlKey", "FromSODocList")
HEADER_SKIP_ON_EDIT = ("Details", "DocKey", "DocNo", "Cancelled", "LastModified", "DocStatus")
FAKE_HOST = "https://ac.example.test/api/db3"
# the keys of a full vendor row (SO shape, plan 57 AC-57-45); a thinner row is dropped by the fake
FULL_ROW_KEYS = ("FullTransferOption", "FullTransferFromDocList", "YourPONo", "ProjNo", "FOCQty",
                 "Discount", "TaxCode", "Desc2")


@dataclass
class Call:
    method: str
    path: str  # the URL path as the vendor saw it, e.g. /api/db3/NewQuotation
    leaf: str  # last path segment, lower-cased
    query: Dict[str, str]
    body: Any
    status: int = 0
    raw_target: str = ""  # path + query exactly as sent (percent-encoded)


@dataclass
class _Injection:
    method: str
    leaf: str
    mode: str  # fail | timeout | apply_then_500
    status: int = 500
    text: str = "injected failure"
    skip: int = 0  # matching calls to let through first


def new_doc(kind: str, doc_key: int, doc_no: str, party: str, rows: List[Dict[str, Any]], *,
            doc_date: str = "2026-11-04T00:00:00", **header: Any) -> Dict[str, Any]:
    """A vendor-shaped document (neutral values). Rows may omit DtlKey (assigned from doc_key)."""
    spec = SPECS[kind]
    doc: Dict[str, Any] = {
        "DocKey": doc_key, "DocNo": doc_no, "DocDate": doc_date, spec["party"]: party,
        "Ref": "", "Description": "", "DisplayTerm": "C.B.D.", "SalesAgent": "",
        "CurrencyCode": "MYR", "CurrencyRate": 1.0, "Remark1": "", "Remark2": "",
        "Remark3": "", "Remark4": "", "Cancelled": "F", "DocStatus": "A",
        "LastModified": "2026-11-04T10:00:00.00",
    }
    if kind == "QT":
        doc.update({"ToDocType": "", "ToDocKey": 0, "ToDtlKey": 0})
    if kind == "SPO":
        doc["ShippingPO"] = "T"
    doc.update(header)
    doc["Details"] = []
    for index, row in enumerate(rows):
        full = {
            "DtlKey": doc_key * 100 + index + 1, "DocKey": doc_key, "Seq": (index + 1) * 16,
            "ItemCode": "ITEM-1", "Location": "HQ", "Description": "", "UOM": "UNIT",
            "Qty": 1.0, "UnitPrice": 10.0, "Discount": "", "TaxCode": "",
            "DeliveryDate": "2026-11-04T00:00:00", "FromDocType": "", "FromDocNo": "",
            "FromDocDtlKey": 0,
        }
        if kind in ("PO", "SPO"):
            full.update({"FromSODtlKey": 0, "FromSODocList": ""})
        full.update(row)
        doc["Details"].append(full)
    return doc


class FakeAutoCountVendor:
    def __init__(self, today: date = date(2026, 11, 4)) -> None:
        self.today = today
        self.docs: Dict[str, List[Dict[str, Any]]] = {"QT": [], "SO": [], "PO": []}
        self.calls: List[Call] = []
        self._injections: List[_Injection] = []
        self._drop_rows_next_create = False
        self._next_key = 20000
        self._numbers: Dict[str, int] = {}
        self._clock = 0
        # fields AutoCount silently ignores on edit (header or row names), settable per test
        self.ignored_fields: set = set()
        # answer every by-date GET with all docs regardless of date (QT has no staged date)
        self.any_date = False
        # rows AutoCount refuses to delete because they were received / delivered; the GET
        # still hides TransferedQty (AQ11), so the caller cannot know. (doc_key, dtl_key) -> message
        self.received_rows: Dict[tuple, str] = {}
        # plan 57 review knobs
        self._drop_link_next = False  # the next linked row is stored WITHOUT its link
        # kinds whose created / added rows are silently dropped unless the full vendor row shape
        # is sent (live db3: a thin SO row is answered 200 and dropped)
        self.require_full_row: set = set()
        # an SO row taken from a QT row inherits that row's UnitPrice and Location (live db3)
        self.inherit_qt_values = False
        # SS-QTSO-DISPLAYTERM: Debtor master rows served by GET /debtorbypage
        self.debtors: List[Dict[str, Any]] = []
        # plan 61: new PO rows with these ItemCodes are refused 500 (atomic-PUT probes P-AT1)
        self.invalid_items: set = set()
        # plan 62: created docs carry CreatedTimeStamp + LastModified = now in AutoCount local time (MYT, no zone, ms)
        self.stamp_created: bool = False
        self.reject_unknown_so_link: bool = False  # plan 62 F-G: a new PO row linked to a missing SO row refuses the whole PUT
        # plan 61: a cancel is answered 200 but the document stays as it was (a vendor that ignores it)
        self.cancel_ignored = False
        # plan 61: (kind, doc_key) -> message, the document is refused for cancel as "transferred"
        self.transferred_docs: Dict[tuple, str] = {}
        self.transport = httpx.MockTransport(self._handle)

    # ---- seeding / inspection ---------------------------------------------
    def seed(self, kind: str, doc: Dict[str, Any]) -> Dict[str, Any]:
        store = SPECS[kind]["store"]
        self.docs[store].append(copy.deepcopy(doc))
        return doc

    def find(self, kind: str, doc_key: int) -> Dict[str, Any]:
        for doc in self.docs[SPECS[kind]["store"]]:
            if doc["DocKey"] == doc_key:
                return doc
        raise KeyError(doc_key)

    def rows(self, kind: str, doc_key: int) -> List[Dict[str, Any]]:
        return self.find(kind, doc_key)["Details"]

    def writes(self) -> List[Call]:
        return [c for c in self.calls if c.method != "GET"]

    def gets(self) -> List[Call]:
        return [c for c in self.calls if c.method == "GET"]

    def no_http(self) -> bool:
        return not self.calls

    def mark_received(self, kind: str, doc_key: int, dtl_key: int,
                      message: str = "Cannot delete: the line has been transferred.") -> None:
        self.received_rows[(doc_key, dtl_key)] = message

    # ---- failure injection --------------------------------------------------
    def fail_next(self, method: str, leaf: str, status: int = 500, text: str = "injected failure",
                  after: int = 0) -> None:
        """``after`` = how many matching calls pass before the failing one."""
        self._injections.append(_Injection(method.upper(), leaf.lower(), "fail", status, text, after))

    def timeout_next(self, method: str, leaf: str, after: int = 0) -> None:
        self._injections.append(_Injection(method.upper(), leaf.lower(), "timeout", skip=after))

    def apply_then_500_next(self, method: str, leaf: str, after: int = 0) -> None:
        self._injections.append(_Injection(method.upper(), leaf.lower(), "apply_then_500", skip=after))

    def drop_rows_next_create(self) -> None:
        self._drop_rows_next_create = True

    def drop_link_next_add(self) -> None:
        """The next row that should carry a link is stored without it (answered 200)."""
        self._drop_link_next = True

    # ---- transport ------------------------------------------------------------
    def _take(self, method: str, leaf: str) -> Optional[_Injection]:
        for inj in self._injections:
            if inj.method == method and inj.leaf == leaf:
                if inj.skip > 0:
                    inj.skip -= 1
                    continue
                self._injections.remove(inj)
                return inj
        return None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method.upper()
        leaf = request.url.path.rsplit("/", 1)[-1].lower()
        body: Any = json.loads(request.content) if request.content else None
        call = Call(method, request.url.path, leaf, dict(request.url.params), body,
                    raw_target=request.url.raw_path.decode("ascii"))
        self.calls.append(call)
        inj = self._take(method, leaf)
        if inj and inj.mode == "timeout":
            raise httpx.ReadTimeout("injected timeout")
        if inj and inj.mode == "fail":
            call.status = inj.status
            return httpx.Response(inj.status, text=inj.text)
        response = self._route(method, leaf, call)
        if inj and inj.mode == "apply_then_500":
            call.status = 500
            return httpx.Response(500, text="applied but answered 500")
        call.status = response.status_code
        return response

    def _route(self, method: str, leaf: str, call: Call) -> httpx.Response:
        if method == "GET":
            if leaf == "debtorbypage":
                return self._debtor_page(call)
            for kind, spec in SPECS.items():
                if spec["get"] == leaf:
                    return self._get(kind, call)
            for kind, spec in SPECS.items():
                if kind != "SPO" and leaf == f"{spec['noun'].lower()}bydocno":
                    return self._get_by_doc_no(kind, call)
            for kind, spec in SPECS.items():
                if kind != "SPO" and leaf == f"{spec['noun'].lower()}bylastmodified":
                    return self._get_by_last_modified(kind, call)
            return httpx.Response(404, text="no such door")
        for kind, spec in SPECS.items():
            if kind == "SPO":
                continue
            noun = spec["noun"].lower()
            if method == "POST" and leaf == f"new{noun}":
                return self._create(kind, call.body)
            if method == "PUT" and leaf == f"edit{noun}bydockey":
                return self._edit(kind, call.body)
            if method == "DELETE" and leaf == f"cancel{noun}bydocno":
                return self._cancel(kind, call)
        return httpx.Response(404, text="no such door")

    # ---- GET ---------------------------------------------------------------
    def _get(self, kind: str, call: Call) -> httpx.Response:
        wanted = call.query.get("DocDate", "")
        out = [
            copy.deepcopy(d) for d in self.docs[SPECS[kind]["store"]]
            if self.any_date or str(d["DocDate"])[:10].replace("-", "") == wanted
        ]
        return httpx.Response(200, json=out)

    def _get_by_last_modified(self, kind: str, call: Call) -> httpx.Response:
        """GET /<doc>byLastModified?lastModified=YYYYMMDD: every document whose LastModified is that day."""
        wanted = call.query.get("lastModified", "")
        out = [
            copy.deepcopy(d) for d in self.docs[SPECS[kind]["store"]]
            if str(d.get("LastModified", ""))[:10].replace("-", "") == wanted
        ]
        return httpx.Response(200, json=out)

    def _get_by_doc_no(self, kind: str, call: Call) -> httpx.Response:
        wanted = call.query.get("DocNo", "")
        out = [copy.deepcopy(d) for d in self.docs[SPECS[kind]["store"]] if d["DocNo"] == wanted]
        return httpx.Response(200, json=out)

    def _debtor_page(self, call: Call) -> httpx.Response:
        page = int(call.query.get("page", "1"))
        size = int(call.query.get("pageSize", "50"))
        total = len(self.debtors)
        pages = max(1, -(-total // size))
        data = copy.deepcopy(self.debtors[(page - 1) * size: page * size])
        return httpx.Response(200, json={
            "TotalCount": total, "Page": page, "PageSize": size, "TotalPages": pages, "Data": data,
        })

    # ---- POST --------------------------------------------------------------
    def _create(self, kind: str, body: Dict[str, Any]) -> httpx.Response:
        spec = SPECS[kind]
        if not body.get("DocNo"):
            return httpx.Response(500, text="Column 'DocNo' does not allow nulls.")
        if not body.get("DisplayTerm"):
            return httpx.Response(500, text="Incomplete header: DisplayTerm required.")
        self._next_key += 1
        doc_key = self._next_key
        doc_no = body["DocNo"]
        if doc_no == "<<New>>":
            self._numbers[kind] = self._numbers.get(kind, 0) + 1
            doc_no = f"{spec['prefix']}-{self._numbers[kind]:06d}"
        header = {k: v for k, v in body.items() if k not in ("Details", "DocNo")}
        party = header.pop(spec["party"], "")
        sent = list(body.get("Details") or [])
        if self._drop_rows_next_create:
            self._drop_rows_next_create = False
            sent = sent[:1]
        if kind in self.require_full_row:
            sent = [r for r in sent if all(k in r for k in FULL_ROW_KEYS)]
        rows = []
        for row in sent:
            rows.append({k: v for k, v in row.items() if k not in LINK_FIELDS})
        doc = new_doc("PO" if kind == "PO" else kind, doc_key, doc_no, party, rows,
                      doc_date=body.get("DocDate", "2026-11-04T00:00:00"), **header)
        for stored, original in zip(doc["Details"], sent):
            self._apply_new_row_link(kind, stored, original)
            if self.inherit_qt_values and kind == "SO" and original.get("FromDocType") == "QT":
                self._inherit(stored, original)
        self._touch(doc)
        if self.stamp_created:
            stamp = self.now_myt()
            doc["CreatedTimeStamp"] = doc["LastModified"] = stamp
        self.docs[spec["store"]].append(doc)
        return httpx.Response(200, text=f"DocNo={doc_no} ,DocKey={doc_key} ... Created Successful.")

    def _apply_new_row_link(self, kind: str, stored: Dict[str, Any], sent: Dict[str, Any]) -> None:
        ftype = sent.get("FromDocType") or ""
        if not ftype:
            return
        if self._drop_link_next:
            self._drop_link_next = False
            return  # the row exists, the link does not
        stored["FromDocType"] = ftype
        stored["FromDocNo"] = sent.get("FromDocNo", "")
        stored["FromDocDtlKey"] = 0  # AutoCount reads FromDocDtlKey back as 0 (P-SO0)
        if kind == "SPO":  # an SPO row keeps FromDocDtlKey (its PO row); no forced location
            stored["FromDocDtlKey"] = int(sent.get("FromDocDtlKey") or 0)
        elif kind == "PO" and ftype == "SO":
            stored["FromSODtlKey"] = int(sent.get("FromDocDtlKey") or 0)
            stored["FromDocDtlKey"] = int(sent.get("FromDocDtlKey") or 0)
            stored["FromDocType"] = ""  # a PO row reads its link as FromSODtlKey only (F5)
            stored["Location"] = "HQ"  # db3 forces HQ on a new row linked to an SO row
            stored["DeliveryDate"] = "0001-01-01T00:00:00"  # and clears the delivery date (F5)
            stored["UnitPrice"] = 0.0  # and resets the unit price to 0 (F5); a later edit PUT can set it

    def _inherit(self, stored: Dict[str, Any], sent: Dict[str, Any]) -> None:
        for qt in self.docs["QT"]:
            if qt["DocNo"] != sent.get("FromDocNo"):
                continue
            for row in qt["Details"]:
                if row["DtlKey"] == sent.get("FromDocDtlKey"):
                    stored["UnitPrice"] = row["UnitPrice"]
                    stored["Location"] = row["Location"]

    # ---- PUT ---------------------------------------------------------------
    def _edit(self, kind: str, body: Dict[str, Any]) -> httpx.Response:
        try:
            doc = self.find(kind, body.get("DocKey"))
        except KeyError:
            return httpx.Response(404, text="Document not found.")
        if doc.get("Cancelled") == "T" or doc.get("DocStatus") == "V":
            return httpx.Response(500, json={"ExceptionMessage": "not allowed to edit expired or void document",
                                             "ExceptionType": "AutoCount.Invoicing.InvalidDocumentStatus"})
        work = copy.deepcopy(doc)  # all or nothing: commit only when every row went through
        for key, value in body.items():
            if key in HEADER_SKIP_ON_EDIT or key in self.ignored_fields:
                continue
            if key in work or key in ("Ref", "Description", "Remark1", "Remark2", "Remark3", "Remark4"):
                work[key] = value
        for sent in body.get("Details") or []:
            dtl = int(sent.get("DtlKey") or 0)
            if sent.get("FullTransferOption") == "D":
                refused = self._refuse_delete(kind, work, dtl)
                if refused is not None:
                    return refused
                work["Details"] = [r for r in work["Details"] if r["DtlKey"] != dtl]
            elif dtl == 0:
                if sent.get("ItemCode") in self.invalid_items:
                    return httpx.Response(500, json={
                        "ExceptionMessage": "Item code does not exist.",
                        "ExceptionType": "AutoCount.Invoicing.NotExistItemCodeException"})
                if self.reject_unknown_so_link and kind == "PO" and sent.get("FromDocType") == "SO" and not any(
                    r["DtlKey"] == int(sent.get("FromDocDtlKey") or 0)
                    for so in self.docs["SO"] for r in so["Details"]
                ):  # plan 62 F-G: one bad new linked row refuses the WHOLE PUT, nothing lands
                    return httpx.Response(500, json={
                        "ExceptionMessage": "The linked Sales Order detail does not exist.",
                        "ExceptionType": "AutoCount.Invoicing.NotExistFromDocDetailException"})
                if kind in self.require_full_row and not all(k in sent for k in FULL_ROW_KEYS):
                    continue  # answered 200, row dropped
                self._next_key += 1
                row = new_doc(kind, 0, "", "", [{}])["Details"][0]
                row.update({k: v for k, v in sent.items() if k not in LINK_FIELDS})
                row.update({"DtlKey": self._next_key, "DocKey": work["DocKey"], "Seq": 16 * (len(work["Details"]) + 1)})
                self._apply_new_row_link("SPO" if work.get("ShippingPO") == "T" else kind, row, sent)
                work["Details"].append(row)
            else:
                target = next((r for r in work["Details"] if r["DtlKey"] == dtl), None)
                if target is None:
                    return httpx.Response(500, text="Detail not found.")
                for key, value in sent.items():
                    if key in LINK_FIELDS or key in ("DtlKey", "DocKey") or key in self.ignored_fields:
                        continue
                    target[key] = value
        doc.clear()
        doc.update(work)
        self._touch(doc)
        return httpx.Response(200, text=f"DocNo={doc['DocNo']} ,DocKey={doc['DocKey']} ... Done Edit.")

    def _refuse_delete(self, kind: str, doc: Dict[str, Any], dtl_key: int) -> Optional[httpx.Response]:
        """None = the "D" row may go; else the vendor's refusal (F7)."""
        refused = self.received_rows.get((doc["DocKey"], dtl_key))
        if refused:
            return httpx.Response(400, text=refused)
        if not any(r["DtlKey"] == dtl_key for r in doc["Details"]):
            return httpx.Response(500, text="Detail not found.")
        if kind == "SO" and any(
            po.get("Cancelled") != "T" and any(r.get("FromSODtlKey") == dtl_key for r in po["Details"])
            for po in self.docs["PO"]
        ):
            return httpx.Response(500, json={
                "ExceptionMessage": "This item has been transferred to Purchase Order, you are not allow to delete it!",
                "ExceptionType": "AutoCount.Invoicing.UnableToDeleteTransferredItemException"})
        if kind == "QT" and any(
            so.get("Cancelled") != "T"
            and any(r.get("FromDocType") == "QT" and r.get("FromDocNo") == doc["DocNo"]
                    and r.get("FromDocDtlKey") == dtl_key for r in so["Details"])
            for so in self.docs["SO"]
        ):
            return httpx.Response(500, json={
                "ExceptionMessage": "This item has been transferred to Sales Order, you are not allow to delete it!",
                "ExceptionType": "AutoCount.Invoicing.UnableToDeletePartialTransferredItemException"})
        return None

    # ---- DELETE /Cancel<Doc>bydocno?DocNo= (no body) ------------------------------
    def _cancel(self, kind: str, call: Call) -> httpx.Response:
        doc_no = call.query.get("DocNo", "")
        doc = next((d for d in self.docs[SPECS[kind]["store"]] if d["DocNo"] == doc_no), None)
        if doc is None:
            return httpx.Response(400, json={"Message": f"DocNo={doc_no} ... failed to cancel."})
        if doc.get("Cancelled") == "T" or doc.get("DocStatus") == "V":
            return httpx.Response(400, json={
                "Message": "Unable to (Cancel Document) for this document, due to current document status (Void)."})
        message = self.transferred_docs.get((kind, doc["DocKey"]))
        if message is None and kind == "QT" and any(
            so.get("Cancelled") != "T" and any(
                r.get("FromDocType") == "QT" and r.get("FromDocNo") == doc_no for r in so["Details"])
            for so in self.docs["SO"]
        ):
            message = "The document was transfered to other document, so it is not allow to cancel."
        if message is None and kind == "SO" and any(
            po.get("Cancelled") != "T" and any(
                r.get("FromSODtlKey") in {x["DtlKey"] for x in doc["Details"]} for r in po["Details"])
            for po in self.docs["PO"]
        ):
            message = "The Sales Order was transfered to Purchase Order, so it is not allow to cancel."
        if message is not None:
            return httpx.Response(400, json={"Message": message})
        if self.cancel_ignored:
            return httpx.Response(200, text=f"DocNo={doc_no} ... was cancelled.")
        doc["Cancelled"], doc["DocStatus"] = "T", "V"
        self._touch(doc)
        return httpx.Response(200, text=f"DocNo={doc_no} ... was cancelled.")

    @staticmethod
    def now_myt() -> str:
        """AutoCount local time (MYT, UTC+8) as the vendor writes it: no zone, milliseconds."""
        from datetime import datetime, timedelta, timezone

        return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat(timespec="milliseconds")

    def _touch(self, doc: Dict[str, Any]) -> None:
        self._clock += 1
        doc["LastModified"] = f"2026-11-04T11:00:{self._clock % 60:02d}.00"

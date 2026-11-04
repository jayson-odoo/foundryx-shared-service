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
* DELETE shapes are the PLACEHOLDERS of plan 57 section 5.1 (AQ23, unverified):
  ``/Delete<Doc>Detailbydtlkey`` body ``{DocKey, DtlKey}`` and
  ``/Delete<Doc>bydockey`` body ``{DocKey}``.

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


@dataclass
class Call:
    method: str
    path: str  # the URL path as the vendor saw it, e.g. /api/db3/NewQuotation
    leaf: str  # last path segment, lower-cased
    query: Dict[str, str]
    body: Any
    status: int = 0


@dataclass
class _Injection:
    method: str
    leaf: str
    mode: str  # fail | timeout | apply_then_500
    status: int = 500
    text: str = "injected failure"


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

    # ---- failure injection --------------------------------------------------
    def fail_next(self, method: str, leaf: str, status: int = 500, text: str = "injected failure") -> None:
        self._injections.append(_Injection(method.upper(), leaf.lower(), "fail", status, text))

    def timeout_next(self, method: str, leaf: str) -> None:
        self._injections.append(_Injection(method.upper(), leaf.lower(), "timeout"))

    def apply_then_500_next(self, method: str, leaf: str) -> None:
        self._injections.append(_Injection(method.upper(), leaf.lower(), "apply_then_500"))

    def drop_rows_next_create(self) -> None:
        self._drop_rows_next_create = True

    # ---- transport ------------------------------------------------------------
    def _take(self, method: str, leaf: str) -> Optional[_Injection]:
        for inj in self._injections:
            if inj.method == method and inj.leaf == leaf:
                self._injections.remove(inj)
                return inj
        return None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method.upper()
        leaf = request.url.path.rsplit("/", 1)[-1].lower()
        body: Any = json.loads(request.content) if request.content else None
        call = Call(method, request.url.path, leaf, dict(request.url.params), body)
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
            for kind, spec in SPECS.items():
                if spec["get"] == leaf:
                    return self._get(kind, call)
            return httpx.Response(404, text="no such door")
        for kind, spec in SPECS.items():
            if kind == "SPO":
                continue
            noun = spec["noun"].lower()
            if method == "POST" and leaf == f"new{noun}":
                return self._create(kind, call.body)
            if method == "PUT" and leaf == f"edit{noun}bydockey":
                return self._edit(kind, call.body)
            if method == "DELETE" and leaf == f"delete{noun}detailbydtlkey":
                return self._delete_line(kind, call.body)
            if method == "DELETE" and leaf == f"delete{noun}bydockey":
                return self._delete_doc(kind, call.body)
        return httpx.Response(404, text="no such door")

    # ---- GET ---------------------------------------------------------------
    def _get(self, kind: str, call: Call) -> httpx.Response:
        wanted = call.query.get("DocDate", "")
        out = [
            copy.deepcopy(d) for d in self.docs[SPECS[kind]["store"]]
            if self.any_date or str(d["DocDate"])[:10].replace("-", "") == wanted
        ]
        return httpx.Response(200, json=out)

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
        rows = []
        for row in sent:
            rows.append({k: v for k, v in row.items() if k not in LINK_FIELDS})
        doc = new_doc("PO" if kind == "PO" else kind, doc_key, doc_no, party, rows,
                      doc_date=body.get("DocDate", "2026-11-04T00:00:00"), **header)
        for stored, original in zip(doc["Details"], sent):
            self._apply_new_row_link(kind, stored, original)
        self._touch(doc)
        self.docs[spec["store"]].append(doc)
        return httpx.Response(200, text=f"DocNo={doc_no} ,DocKey={doc_key} ... Created Successful.")

    def _apply_new_row_link(self, kind: str, stored: Dict[str, Any], sent: Dict[str, Any]) -> None:
        ftype = sent.get("FromDocType") or ""
        if not ftype:
            return
        stored["FromDocType"] = ftype
        stored["FromDocNo"] = sent.get("FromDocNo", "")
        stored["FromDocDtlKey"] = 0  # AutoCount reads FromDocDtlKey back as 0 (P-SO0)
        if kind in ("PO", "SPO") and ftype in ("SO", "PO"):
            stored["FromSODtlKey"] = int(sent.get("FromDocDtlKey") or 0)
            stored["FromDocDtlKey"] = int(sent.get("FromDocDtlKey") or 0)
            stored["Location"] = "HQ"  # db3 forces HQ on a new linked row

    # ---- PUT ---------------------------------------------------------------
    def _edit(self, kind: str, body: Dict[str, Any]) -> httpx.Response:
        try:
            doc = self.find(kind, body.get("DocKey"))
        except KeyError:
            return httpx.Response(404, text="Document not found.")
        for key, value in body.items():
            if key in HEADER_SKIP_ON_EDIT or key in self.ignored_fields:
                continue
            if key in doc or key in ("Ref", "Description", "Remark1", "Remark2", "Remark3", "Remark4"):
                doc[key] = value
        for sent in body.get("Details") or []:
            if int(sent.get("DtlKey") or 0) == 0:
                self._next_key += 1
                row = new_doc(kind, 0, "", "", [{}])["Details"][0]
                row.update({k: v for k, v in sent.items() if k not in LINK_FIELDS})
                row.update({"DtlKey": self._next_key, "DocKey": doc["DocKey"], "Seq": 16 * (len(doc["Details"]) + 1)})
                self._apply_new_row_link(kind, row, sent)
                doc["Details"].append(row)
            else:
                target = next((r for r in doc["Details"] if r["DtlKey"] == sent["DtlKey"]), None)
                if target is None:
                    return httpx.Response(500, text="Detail not found.")
                for key, value in sent.items():
                    if key in LINK_FIELDS or key in ("DtlKey", "DocKey") or key in self.ignored_fields:
                        continue
                    target[key] = value
        self._touch(doc)
        return httpx.Response(200, text=f"DocNo={doc['DocNo']} ,DocKey={doc['DocKey']} ... Done Edit.")

    # ---- DELETE (placeholder shapes) -----------------------------------------
    def _delete_line(self, kind: str, body: Dict[str, Any]) -> httpx.Response:
        try:
            doc = self.find(kind, body["DocKey"])
        except KeyError:
            return httpx.Response(404, text="Document not found.")
        before = len(doc["Details"])
        doc["Details"] = [r for r in doc["Details"] if r["DtlKey"] != body["DtlKey"]]
        if len(doc["Details"]) == before:
            return httpx.Response(404, text="Detail not found.")
        self._touch(doc)
        return httpx.Response(200, text="Deleted.")

    def _delete_doc(self, kind: str, body: Dict[str, Any]) -> httpx.Response:
        store = self.docs[SPECS[kind]["store"]]
        keep = [d for d in store if d["DocKey"] != body["DocKey"]]
        if len(keep) == len(store):
            return httpx.Response(404, text="Document not found.")
        store[:] = keep
        return httpx.Response(200, text="Deleted.")

    def _touch(self, doc: Dict[str, Any]) -> None:
        self._clock += 1
        doc["LastModified"] = f"2026-11-04T11:00:{self._clock % 60:02d}.00"

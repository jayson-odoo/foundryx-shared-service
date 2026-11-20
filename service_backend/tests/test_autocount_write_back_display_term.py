"""SS-QTSO-DISPLAYTERM: a QT / SO write without ``displayTerm`` takes the debtor's own
AutoCount term.

The CRM has no debtor credit term, and AutoCount's ``DisplayTerm`` must be a code from
AutoCount's own Terms list. So when a quotation / sales order create (or edit) from the
caller carries no ``displayTerm``, SS reads the debtor from the SAME book
(``GET /debtorbypage``) and sends that debtor's ``DisplayTerm``. A debtor without a term
(or unknown to the book) is refused ``DEBTOR_TERM_MISSING`` naming the debtor code, before
any write. An explicit ``displayTerm`` is always kept. Purchase orders are unchanged
(creditor side: ``FIELD_REQUIRED``).
"""

from __future__ import annotations

import pytest

from tests.test_autocount_write_back_gateway_qtso import (  # noqa: F401
    PREFIX,
    SLUG,
    Gw,
    code,
    create_body,
    db,
    gw,
    h,
)
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def _debtor(acc_no: str, term: object = "NET 30", **extra) -> dict:
    row = {"AccNo": acc_no, "CompanyName": f"{acc_no} SDN BHD", "DisplayTerm": term, "IsActive": "T"}
    row.update(extra)
    return row


def _no_term_body(kind: str = "QT", debtor: str = "PARTY-1") -> dict:
    body = create_body(kind)
    del body["header"]["displayTerm"]
    body["header"]["debtorCode"] = debtor
    return body


def _debtor_gets(gw) -> list:
    return [c for c in gw.h.vendor.gets() if c.leaf == "debtorbypage"]


@pytest.mark.parametrize("kind", ["QT", "SO"])
def test_no_display_term_sends_the_debtors_own_autocount_term(client, gw, kind):
    gw.h.vendor.debtors = [_debtor("OTHER", "C.O.D."), _debtor("PARTY-1", "NET 30")]
    r = client.post(f"{PREFIX}/documents/{SLUG[kind]}", json=_no_term_body(kind), headers=gw.hdr(f"t-{kind}"))
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    sent = gw.h.vendor.writes()[0].body
    assert sent["DisplayTerm"] == "NET 30" and sent["DebtorCode"] == "PARTY-1"


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_display_term_counts_as_absent(client, gw, blank):
    gw.h.vendor.debtors = [_debtor("PARTY-1", "C.B.D.")]
    body = create_body("QT")
    body["header"]["displayTerm"] = blank
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "C.B.D."


def test_the_debtor_is_found_past_the_first_page(client, gw):
    gw.h.vendor.debtors = [_debtor(f"D-{i:05d}", "C.O.D.") for i in range(2500)] + [_debtor("PARTY-1", "NET 60")]
    r = client.post(f"{PREFIX}/documents/quotations", json=_no_term_body(), headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "NET 60"
    assert len(_debtor_gets(gw)) >= 2


@pytest.mark.parametrize("kind", ["QT", "SO"])
def test_explicit_display_term_is_kept_and_no_debtor_read(client, gw, kind):
    gw.h.vendor.debtors = [_debtor("PARTY-1", "NET 30")]
    r = client.post(f"{PREFIX}/documents/{SLUG[kind]}", json=create_body(kind), headers=gw.hdr(f"e-{kind}"))
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "30 DAYS"
    assert _debtor_gets(gw) == []


@pytest.mark.parametrize("term", ["", "  ", None])
@pytest.mark.parametrize("kind", ["QT", "SO"])
def test_debtor_without_a_term_is_422_debtor_term_missing_and_nothing_written(client, gw, kind, term):
    gw.h.vendor.debtors = [_debtor("PARTY-1", term)]
    r = client.post(f"{PREFIX}/documents/{SLUG[kind]}", json=_no_term_body(kind), headers=gw.hdr(f"m-{kind}"))
    assert r.status_code == 422, r.text
    assert code(r) == "DEBTOR_TERM_MISSING"
    assert "PARTY-1" in r.json()["message"]
    assert "FIELD_REQUIRED" not in r.text
    assert gw.h.vendor.writes() == []


def test_debtor_unknown_to_the_book_is_debtor_term_missing(client, gw):
    gw.h.vendor.debtors = [_debtor("OTHER", "NET 30")]
    r = client.post(f"{PREFIX}/documents/quotations", json=_no_term_body(), headers=gw.hdr())
    assert r.status_code == 422 and code(r) == "DEBTOR_TERM_MISSING", r.text
    assert "PARTY-1" in r.json()["message"]
    assert gw.h.vendor.writes() == []


def test_debtor_read_failure_is_refused_without_a_write(client, gw):
    gw.h.vendor.fail_next("GET", "debtorbypage")
    r = client.post(f"{PREFIX}/documents/quotations", json=_no_term_body(), headers=gw.hdr())
    assert r.status_code == 409 and code(r) == "READ_FAILED", r.text
    assert gw.h.vendor.writes() == []


def test_other_missing_fields_are_refused_before_any_debtor_read(client, gw):
    gw.h.vendor.debtors = [_debtor("PARTY-1", "NET 30")]
    body = _no_term_body()
    del body["header"]["currencyCode"]
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 422 and code(r) == "FIELD_REQUIRED" and "currencyCode" in r.text
    gw.h.no_http()


def test_purchase_order_without_display_term_stays_field_required(client, gw):
    body = create_body("PO")
    del body["header"]["displayTerm"]
    r = client.post(f"{PREFIX}/documents/purchase-orders", json=body, headers=gw.hdr())
    assert r.status_code == 422 and code(r) == "FIELD_REQUIRED" and "displayTerm" in r.text
    gw.h.no_http()


# ---- edit (update) --------------------------------------------------------------------------------


def _seed_so(gw, **header):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)], **header)


def test_edit_blanking_display_term_sends_the_debtors_term(client, gw):
    _seed_so(gw)
    gw.h.vendor.debtors = [_debtor("PARTY-1", "NET 45")]
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"displayTerm": "", "ref": "x"}})
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "NET 45"


def test_edit_on_a_document_without_a_term_fills_it_from_the_debtor(client, gw):
    _seed_so(gw, DisplayTerm="")
    gw.h.vendor.debtors = [_debtor("PARTY-1", "NET 45")]
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "NET 45"


def test_edit_keeps_the_documents_term_and_reads_no_debtor(client, gw):
    _seed_so(gw)
    gw.h.vendor.debtors = [_debtor("PARTY-1", "NET 45")]
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    assert gw.h.vendor.writes()[0].body["DisplayTerm"] == "C.B.D."
    assert _debtor_gets(gw) == []


def test_edit_blanking_with_a_termless_debtor_is_debtor_term_missing(client, gw):
    _seed_so(gw)
    gw.h.vendor.debtors = [_debtor("PARTY-1", "")]
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"displayTerm": ""}})
    assert r.status_code == 422 and code(r) == "DEBTOR_TERM_MISSING", r.text
    assert gw.h.vendor.writes() == []



def test_the_debtor_walk_runs_the_deadline_hook_before_every_later_page():
    from modules.autocount.write_back.reader import AutoCountDocReader
    from tests.autocount_write_back_fake_vendor import FAKE_HOST, FakeAutoCountVendor

    vendor = FakeAutoCountVendor()
    vendor.debtors = [_debtor(f"D-{i:05d}", "C.O.D.") for i in range(2500)] + [_debtor("PARTY-1", "NET 60")]
    reader = AutoCountDocReader(FAKE_HOST, transport=vendor.transport)
    seen = []
    assert reader.debtor_term("party-1 ", before_page=lambda: seen.append(1)) == (True, "NET 60")
    assert len(seen) == 2  # pages 2 and 3, never before page 1

    class Stop(Exception):
        pass

    def deadline():
        raise Stop()

    vendor.calls.clear()
    with pytest.raises(Stop):
        reader.debtor_term("PARTY-1", before_page=deadline)
    assert len(vendor.calls) == 1  # stopped before page 2


def test_debtor_page_without_total_pages_is_read_failed():
    import httpx

    from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError

    body = {"Data": [_debtor("OTHER")]}
    reader = AutoCountDocReader("https://ac.example.test/api/db3",
                                transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
    with pytest.raises(DocReadError):
        reader.debtor_term("PARTY-1")

"""Lane SS-BILLING-DO-API - a billing line's DO hop resolves from the DO feed
ledger, never from `DODTL` (owner ruling 25 Oct: the AutoCount admin will not
grant DODTL, but the hapi DO feed already files every delivered DO's
(book, DocKey, DocNo) in `ac_doc_feed_ledger`).

`billing_do_doc_keys` is the DB half: DO number -> the DocKeys the CRM holds
under the company's Delivery Orders feed book. The mapping engine (the other
half, `tests/test_autocount_billing_feed.py`) links only on exactly one.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
)
from modules.autocount.doc_feed.constants import FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES
from modules.autocount.http_source.book import billing_do_doc_keys
from modules.autocount.models import AcDocFeedLedger

from .s16_do_pull_helpers import add_feed, make_company, s16_isolation  # noqa: F401

BOOK = "fakebook"
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _ledger(db, company, doc_key, doc_no, *, feed=FEED_DELIVERY_ORDERS, book=BOOK,
            company_id=None, vanished=False):
    db.add(AcDocFeedLedger(
        tenant_id=company.tenant_id, company_id=company_id or company.id, feed=feed,
        book=book, doc_key=doc_key, doc_no=doc_no, doc_date=date(2026, 9, 1),
        source_modified_at=NOW, last_outcome="created", pushed_at=NOW,
        vanished_at=NOW + timedelta(days=1) if vanished else None,
    ))
    db.commit()


def test_only_invoice_and_cash_sale_get_a_lookup(db):
    company, conn = make_company(db)
    add_feed(db, company, conn, feed=FEED_DELIVERY_ORDERS, book=BOOK)
    assert billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE) is not None
    assert billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_CASH_SALE) is not None
    assert billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_CREDIT_NOTE) is None
    assert billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_DEBIT_NOTE) is None


def test_no_do_feed_book_means_no_lookup(db):
    company, _conn = make_company(db)
    assert billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE) is None


def test_the_lookup_reads_only_this_companys_live_do_rows_in_the_do_book(db):
    company, conn = make_company(db)
    add_feed(db, company, conn, feed=FEED_DELIVERY_ORDERS, book=BOOK)
    _ledger(db, company, 9001, "DO-2609/0077")
    # Noise that must never match:
    _ledger(db, company, 9002, "DO-2609/0077", book="otherbook")  # another book
    _ledger(db, company, 9003, "DO-2609/0077", feed=FEED_GOODS_RECEIVE_NOTES)  # GRN feed
    _ledger(db, company, 9004, "DO-2609/0077", company_id="another-company")
    _ledger(db, company, 9005, "DO-2609/0077", vanished=True)  # deleted in AutoCount
    lookup = billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE)
    assert lookup("DO-2609/0077") == [9001]
    # Trimmed + case-insensitive, like the doc finder's ledger read.
    assert lookup("  do-2609/0077 ") == [9001]
    assert lookup("DO-2609/9999") == []


def test_the_lookup_is_tenant_scoped(db):
    company, conn = make_company(db)
    add_feed(db, company, conn, feed=FEED_DELIVERY_ORDERS, book=BOOK)
    db.add(AcDocFeedLedger(
        tenant_id="another-tenant", company_id=company.id, feed=FEED_DELIVERY_ORDERS,
        book=BOOK, doc_key=9100, doc_no="DO-1", last_outcome="created", pushed_at=NOW,
    ))
    db.commit()
    lookup = billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE)
    assert lookup("DO-1") == []


def test_two_live_dos_with_one_number_are_both_returned(db):
    """The engine refuses to guess between them; the lookup must not hide one."""
    company, conn = make_company(db)
    add_feed(db, company, conn, feed=FEED_DELIVERY_ORDERS, book=BOOK)
    _ledger(db, company, 9001, "DO-1")
    _ledger(db, company, 9002, "DO-1")
    lookup = billing_do_doc_keys(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE)
    assert sorted(lookup("DO-1")) == [9001, 9002]

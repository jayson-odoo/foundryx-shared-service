"""SS-BACKFILL-DATE-FLOOR - every backfill dialog accepts days back to 2000.

The owner could not pick 2010 on the GRN backfill: the floor was 2019-01-01
(2006-01-01 for project registrations). The floor is now 2000-01-01 for every
feed; a day before it still 422s (no unbounded vendor sweep), and a long range
is still one chunked, resumable backfill (dry run first).
"""
from __future__ import annotations

from datetime import date

import pytest

from modules.autocount.doc_feed import constants as C
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill
from modules.autocount.services.doc_feed_service import DocFeedService

from .s14_doc_feed_helpers import wired_company

ACTOR_USER_ID = "actor-1"


def _feed(db, company, ac_conn, feed: str) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed=feed,
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("feed", sorted(C.DOCUMENT_FEEDS))
def test_every_document_feed_floor_is_2000(feed):
    assert C.backfill_floor(feed) == date(2000, 1, 1)


@pytest.mark.parametrize("feed", sorted(C.DOCUMENT_FEEDS))
def test_a_dry_run_from_2010_starts_on_every_feed(session_factory, feed):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn, feed)

    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, feed, dry_run=True,
        from_day=date(2010, 1, 1), to_day=date(2010, 1, 3), actor_user_id=ACTOR_USER_ID,
    )

    assert bf.from_day == date(2010, 1, 1)
    assert bf.days_total == 3


def test_the_default_from_day_is_the_2000_floor(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn, C.FEED_GOODS_RECEIVE_NOTES)

    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, C.FEED_GOODS_RECEIVE_NOTES, dry_run=True,
        actor_user_id=ACTOR_USER_ID,
    )

    assert bf.from_day == date(2000, 1, 1)
    # One row, walked day by day in budgeted segments (SS-BACKFILL-CHUNKED).
    assert bf.next_day == date(2000, 1, 1)
    assert bf.days_total == (bf.to_day - date(2000, 1, 1)).days + 1


def test_a_day_before_2000_still_422s(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn, C.FEED_GOODS_RECEIVE_NOTES)

    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, C.FEED_GOODS_RECEIVE_NOTES, dry_run=True,
            from_day=date(1999, 12, 31), to_day=date(2000, 1, 2), actor_user_id=ACTOR_USER_ID,
        )
    assert "2000-01-01" in str(exc_info.value)
    assert db.query(AcDocFeedBackfill).count() == 0


def test_the_feed_view_sends_the_2000_floor(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn, C.FEED_GOODS_RECEIVE_NOTES)

    view = DocFeedService(db).view(co.tenant_id, co.id)
    item = next(i for i in view.feeds if i.feed == C.FEED_GOODS_RECEIVE_NOTES)
    assert item.backfillFloor == date(2000, 1, 1)

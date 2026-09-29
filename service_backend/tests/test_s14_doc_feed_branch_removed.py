"""sprint-5/14 section 11 (D28, AC-14-46) - nothing branch-shaped remains on
the doc feed.

Branches left the doc-feed engine and became the regular HTTP master entity
`branch` (tests/test_autocount_branch.py). This file pins the REMOVAL: the
router, the wire, the backfill, the beat, the run kinds, the model index and
the unmerged migration. The old branch-pull / branch-step tests were deleted
from test_s14_doc_feed_poll.py / _backfill.py / _scheduler.py /
_clock_records.py for the same reason.

Every removal assertion has a positive control (the two surviving feeds still
work) so none of them can pass for the wrong reason.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from .s14_doc_feed_helpers import auth_headers, autocount_connection, company, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
BACKEND = Path(__file__).resolve().parent.parent


def test_ac_14_46_get_view_answers_exactly_two_feeds(client, session_factory):
    db = session_factory()
    co = company(db)
    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=auth_headers(client)).json()
    assert [f["feed"] for f in body["feeds"]] == ["delivery_orders", "goods_receive_notes"]


def test_ac_14_46_put_branches_feed_is_404_while_a_real_feed_still_saves(client, session_factory):
    db = session_factory()
    co = company(db)
    conn = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none")
    db.commit()
    headers = auth_headers(client)

    ok = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": conn.id, "mode": "off"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text  # control: the route itself is live

    gone = client.put(
        f"/autocount/doc-feeds/{co.id}/branches",
        json={"connectionId": conn.id, "mode": "off"}, headers=headers,
    )
    assert gone.status_code == 404, gone.text


def test_ac_14_46_backfill_view_has_no_branch_step_field(client, session_factory):
    from modules.autocount.models import AcDocFeed, AcDocFeedBackfill

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
    )
    db.add(feed)
    db.commit()
    db.add(AcDocFeedBackfill(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
        book="db1", dry_run=False, from_day=date(2026, 9, 1), to_day=date(2026, 9, 3),
        next_day=date(2026, 9, 1), status="stopped", days_total=3, days_done=0,
        started_by="actor-1", started_at=NOW,
    ))
    db.commit()

    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=auth_headers(client)).json()
    item = next(f for f in body["feeds"] if f["feed"] == "delivery_orders")
    assert item["backfill"] is not None, item  # control: a backfill IS surfaced
    assert "daysTotal" in item["backfill"]
    assert "branchStep" not in item["backfill"], item["backfill"]


def test_ac_14_46_backfill_schema_declares_no_branch_step():
    from modules.autocount.schemas import DocFeedBackfillOut

    assert "daysTotal" in DocFeedBackfillOut.model_fields  # control
    assert "branchStep" not in DocFeedBackfillOut.model_fields


def test_ac_14_46_run_kinds_are_poll_sweep_backfill_only():
    from modules.autocount.doc_feed import constants

    assert constants.RUN_KINDS == ("poll", "sweep", "backfill")
    assert not hasattr(constants, "RUN_KIND_BRANCH")


def test_ac_14_46_branch_feed_symbols_are_gone():
    import modules.autocount.models as models
    from modules.autocount.doc_feed import constants, runner
    from modules.autocount.doc_feed.vendor import DocFeedVendor

    assert not hasattr(models, "DOC_FEED_BRANCHES")
    assert models.DOC_FEED_KEYS == ("delivery_orders", "goods_receive_notes")
    assert not hasattr(constants, "FEED_BRANCHES")
    assert not hasattr(constants, "BRANCH_BY_PAGE_PATH")
    assert not hasattr(runner, "run_branch_pull")
    assert not hasattr(DocFeedVendor, "branches")
    with pytest.raises(ImportError):
        from modules.autocount.doc_feed.runner import run_branch_pull  # noqa: F401
    with pytest.raises(ImportError):
        from modules.autocount.models import DOC_FEED_BRANCHES  # noqa: F401


def test_ac_14_46_sink_tables_no_longer_key_the_plural_branches_feed():
    from modules.autocount.sinks_sorento import CONTRACT_GATED_ENTITIES, _ENTITY_PATH

    # `branches` (plural) was the doc-feed key; the entity key is `branch`.
    assert "branches" not in _ENTITY_PATH
    assert "branches" not in CONTRACT_GATED_ENTITIES
    assert "branch" in _ENTITY_PATH  # control: the replacement is registered


def test_ac_14_46_unmerged_migration_0023_carries_no_branch_step_column():
    text = (BACKEND / "modules" / "autocount" / "alembic" / "versions" / "0023_autocount_doc_feed.py").read_text()
    assert "ac_doc_feed_backfill" in text  # control: reading the right file
    assert "branch_step" not in text

"""Vendor path constants + feed keys (plan section 1, AC-14-10).

Casing differs per door - these strings are pinned by
``tests/test_s14_doc_feed_clock_records.py`` and must never drift (a
query-string change here is a live-vendor outage).
"""
from __future__ import annotations

from datetime import date
from typing import Dict

# ── feed keys (the door names, also the Sorento ingest path segments) ───────
FEED_DELIVERY_ORDERS = "delivery_orders"
FEED_GOODS_RECEIVE_NOTES = "goods_receive_notes"
# Plan 72 (AUTOCOUNT-PROJECT-SYNC S0) - AutoCount project registrations.
# Identity is the text ``ProjNo`` (no DocKey) and the only door is by date.
FEED_PROJECT_REGISTRATIONS = "project_registrations"

DOCUMENT_FEEDS = (FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES, FEED_PROJECT_REGISTRATIONS)
ALL_FEEDS = (FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES, FEED_PROJECT_REGISTRATIONS)
# Feeds whose identity is ``ProjNo`` (``records.doc_key``) and that have no
# deletions door: the re-check (sweep) never runs a deletion step for them.
PROJNO_FEEDS = (FEED_PROJECT_REGISTRATIONS,)
# Feeds read by date only (no LastModified door): the poll basis is forced.
DATE_ONLY_FEEDS = (FEED_PROJECT_REGISTRATIONS,)

# ── vendor GET paths (relative to the feed connection's own base URL) ───────
DO_BY_LAST_MODIFIED_PATH = "/deliveryorderbyLastModified"
DO_BY_DOC_DATE_PATH = "/deliveryorderbydocdate"
GRN_BY_LAST_MODIFIED_PATH = "/goodsreceivenotebyLastModified"
GRN_BY_DOC_DATE_PATH = "/goodsreceivenotebydocdate"
PROJECT_REG_BY_DATE_PATH = "/ProjectRegbyDate"

BY_LAST_MODIFIED_PATH = {
    FEED_DELIVERY_ORDERS: DO_BY_LAST_MODIFIED_PATH,
    FEED_GOODS_RECEIVE_NOTES: GRN_BY_LAST_MODIFIED_PATH,
}
BY_DOC_DATE_PATH = {
    FEED_DELIVERY_ORDERS: DO_BY_DOC_DATE_PATH,
    FEED_GOODS_RECEIVE_NOTES: GRN_BY_DOC_DATE_PATH,
    FEED_PROJECT_REGISTRATIONS: PROJECT_REG_BY_DATE_PATH,
}
# The query parameter each by-date door takes (``yyyymmdd``).
BY_DOC_DATE_PARAM = {
    FEED_DELIVERY_ORDERS: "DocDate",
    FEED_GOODS_RECEIVE_NOTES: "DocDate",
    FEED_PROJECT_REGISTRATIONS: "Date",
}

# ── modes (D2) ───────────────────────────────────────────────────────────────
MODE_OFF = "off"
MODE_DRY_RUN = "dry_run"
MODE_PUSH = "push"
MODES = (MODE_OFF, MODE_DRY_RUN, MODE_PUSH)

# ── run kinds / outcomes ─────────────────────────────────────────────────────
RUN_KIND_POLL = "poll"
RUN_KIND_SWEEP = "sweep"
RUN_KIND_BACKFILL = "backfill"
RUN_KINDS = (RUN_KIND_POLL, RUN_KIND_SWEEP, RUN_KIND_BACKFILL)

# ── issue kinds ───────────────────────────────────────────────────────────────
ISSUE_RETRYABLE = "retryable"
ISSUE_FAILED = "failed"

# ── backfill (Q6) ────────────────────────────────────────────────────────────
# SS-BACKFILL-DATE-FLOOR - every feed reaches back to 2000 (was 2019; project
# registrations 2006). Still a floor, not open-ended: each day is one vendor
# GET, walked in budgeted resumable segments (SS-BACKFILL-CHUNKED).
BACKFILL_FROM_DEFAULT = "2000-01-01"
# Per-feed override (none today); a feed missing here uses the default.
BACKFILL_FLOOR_BY_FEED: Dict[str, str] = {}
BACKFILL_STATUS_RUNNING = "running"
BACKFILL_STATUS_STOPPING = "stopping"
BACKFILL_STATUS_STOPPED = "stopped"
BACKFILL_STATUS_DONE = "done"
BACKFILL_OPEN_STATUSES = (
    BACKFILL_STATUS_RUNNING, BACKFILL_STATUS_STOPPING, BACKFILL_STATUS_STOPPED,
)

# ── deletion sweep (scout Q9, D12) ───────────────────────────────────────────
SWEEP_WINDOW_DAYS = 45

# ── job types (D15) ──────────────────────────────────────────────────────────
DOC_FEED_RUN_JOB_TYPE = "autocount_doc_feed_run"
DOC_FEED_BACKFILL_JOB_TYPE = "autocount_doc_feed_backfill"


def backfill_floor(feed: str) -> date:
    """The earliest day a backfill of ``feed`` may start on (its default from-day)."""
    return date.fromisoformat(BACKFILL_FLOOR_BY_FEED.get(feed, BACKFILL_FROM_DEFAULT))

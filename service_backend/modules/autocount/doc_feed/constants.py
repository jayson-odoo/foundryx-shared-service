"""Vendor path constants + feed keys (plan section 1, AC-14-10).

Casing differs per door - these strings are pinned by
``tests/test_s14_doc_feed_clock_records.py`` and must never drift (a
query-string change here is a live-vendor outage).
"""
from __future__ import annotations

# ── feed keys (the door names, also the Sorento ingest path segments) ───────
FEED_DELIVERY_ORDERS = "delivery_orders"
FEED_GOODS_RECEIVE_NOTES = "goods_receive_notes"

DOCUMENT_FEEDS = (FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES)
ALL_FEEDS = (FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES)

# ── vendor GET paths (relative to the feed connection's own base URL) ───────
DO_BY_LAST_MODIFIED_PATH = "/deliveryorderbyLastModified"
DO_BY_DOC_DATE_PATH = "/deliveryorderbydocdate"
GRN_BY_LAST_MODIFIED_PATH = "/goodsreceivenotebyLastModified"
GRN_BY_DOC_DATE_PATH = "/goodsreceivenotebydocdate"

BY_LAST_MODIFIED_PATH = {
    FEED_DELIVERY_ORDERS: DO_BY_LAST_MODIFIED_PATH,
    FEED_GOODS_RECEIVE_NOTES: GRN_BY_LAST_MODIFIED_PATH,
}
BY_DOC_DATE_PATH = {
    FEED_DELIVERY_ORDERS: DO_BY_DOC_DATE_PATH,
    FEED_GOODS_RECEIVE_NOTES: GRN_BY_DOC_DATE_PATH,
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
BACKFILL_FROM_DEFAULT = "2023-01-01"
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

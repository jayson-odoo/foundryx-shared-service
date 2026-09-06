"""Broadcast audience resolution + the send-time snapshot (plan 29, roadmap A4).

The audience is stored as CONFIGURATION only (D-A4-2) - exactly one of a
saved segment, an inline `FilterGroup`, or an explicit contact-id list. This
module composes A2's `ContactListService.query_for_export` (the ONE
whitelisted query builder every consumer of the contact filter map shares -
never a second column map, never a Python-side scan) to resolve that
configuration into an actual SQL `Contact` query, for both:

  * `preview_count()` - a live count while the builder is being configured
    (never a stored list, D-A4-2, AC-BRD-23);
  * `snapshot_audience()` - the send-time materialization into
    `broadcast_recipients` rows (S2 wires this into the send job's snapshot
    phase; THIS slice ships + tests the function in isolation, per the
    plan's send-job contract §5.4 step 2).

`snapshot_audience` is idempotent (ON CONFLICT DO NOTHING on the recipients'
`UNIQUE(broadcast_id, contact_id)`) and self-reports every skip it can
determine BEFORE a message is ever attempted: `no_identity` (no
`ContactChannelIdentity` row on the broadcast's channel), `channel_inactive`
(the channel is no longer active/live), and `duplicate` (a contact already
snapshotted for this broadcast - covers a resumed/retried snapshot AND a
same-call repeat, which is how idempotent re-run is verified). `missing_
variable` and `cancelled` are written later, at SEND/CANCEL time (S2) - a
resolved audience row has no rendered bindings yet at snapshot time.
"""
from typing import Dict, List, Optional

from sqlalchemy import false as sa_false, func
from sqlalchemy.orm import Query, Session

from app.schemas.filters import FilterGroup

from ..models import Broadcast, BroadcastRecipient, Channel, Contact, ContactChannelIdentity
from .contact_list_service import ContactListService

SNAPSHOT_BATCH_SIZE = 200

# The full skip-reason vocabulary (plan §5.6) - only `no_identity`,
# `channel_inactive` and `duplicate` are producible by THIS function;
# `missing_variable` (send-time binding resolution) and `cancelled`
# (mid-run cancellation) are S2's.
SKIP_REASONS = ("no_identity", "duplicate", "channel_inactive", "cancelled", "missing_variable")


def _audience_query(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    *,
    kind: str,
    segment_id: Optional[str] = None,
    filter_group: Optional[FilterGroup] = None,
    contact_ids: Optional[List[str]] = None,
) -> Query:
    """The ONE query builder for a broadcast audience - composes A2's
    `ContactListService.query_for_export` (never a Python-side scan, never a
    forked column map). Raises `SegmentNotFound` / `FilterError` exactly like
    every other A2 consumer of that builder."""
    svc = ContactListService(db)
    if kind == "contacts":
        if not contact_ids:
            return db.query(Contact).filter(sa_false())
        return svc.query_for_export(tenant_id, workspace_id, ids=contact_ids)
    if kind == "segment":
        return svc.query_for_export(tenant_id, workspace_id, segment_id=segment_id)
    return svc.query_for_export(tenant_id, workspace_id, filter_group=filter_group)


def preview_count(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    *,
    kind: str,
    segment_id: Optional[str] = None,
    filter_group: Optional[FilterGroup] = None,
    contact_ids: Optional[List[str]] = None,
) -> int:
    """A live SQL count for the audience currently being configured - never a
    stored list (D-A4-2), never a Python-side scan (AC-BRD-23)."""
    query = _audience_query(
        db, tenant_id, workspace_id,
        kind=kind, segment_id=segment_id, filter_group=filter_group, contact_ids=contact_ids,
    )
    return query.count()


def broadcast_audience_query(db: Session, broadcast: Broadcast) -> Query:
    """The resolved `Contact` query for an already-SAVED broadcast's audience
    configuration - shared by `snapshot_audience` (this slice) and S2's send
    job."""
    filter_group = (
        FilterGroup.model_validate(broadcast.audience_filter_json)
        if broadcast.audience_filter_json
        else None
    )
    return _audience_query(
        db, broadcast.tenant_id, broadcast.workspace_id,
        kind=broadcast.audience_kind,
        segment_id=broadcast.audience_segment_id,
        filter_group=filter_group,
        contact_ids=broadcast.audience_contact_ids_json,
    )


def recompute_counts(db: Session, broadcast: Broadcast) -> None:
    """Denormalized counts, recomputed set-based from a LIVE aggregate over
    `broadcast_recipients` (D-A4-11) - never accumulated incrementally, so a
    partial run or a retried chunk can never drift from the truth
    (AC-BRD-39's invariant)."""
    rows = (
        db.query(BroadcastRecipient.state, func.count(BroadcastRecipient.id))
        .filter(
            BroadcastRecipient.tenant_id == broadcast.tenant_id,
            BroadcastRecipient.broadcast_id == broadcast.id,
        )
        .group_by(BroadcastRecipient.state)
        .all()
    )
    by_state: Dict[str, int] = {state: count for state, count in rows}
    broadcast.total_count = sum(by_state.values())
    broadcast.sent_count = by_state.get("sent", 0)
    broadcast.delivered_count = by_state.get("delivered", 0)
    broadcast.read_count = by_state.get("read", 0)
    broadcast.failed_count = by_state.get("failed", 0)
    broadcast.skipped_count = by_state.get("skipped", 0)


def snapshot_audience(db: Session, broadcast: Broadcast) -> Dict[str, object]:
    """Resolve the audience ONCE (D-A4-2) and materialize `broadcast_recipients`
    rows - batched inserts, idempotent (ON CONFLICT DO NOTHING on
    `UNIQUE(broadcast_id, contact_id)` so a resumed/retried snapshot never
    double-writes). Writes `skipped/no_identity` + `skipped/channel_inactive`
    rows in the SAME pass (plan §5.4 step 2); `missing_variable`/`cancelled`
    are written later, at send/cancel time (S2).

    Returns `{"total": int, "skippedByReason": {reason: count}}` - `total` is
    the LIVE row count for this broadcast after the pass (never a running
    Python sum), so calling this twice in a row is a safe, cheap no-op on the
    second call (every candidate is now counted as `duplicate`, no new rows).
    Flushes but does NOT commit - the caller (the job handler in S2; a test in
    this slice) owns the transaction boundary.
    """
    channel = (
        db.query(Channel)
        .filter(Channel.id == broadcast.channel_id, Channel.tenant_id == broadcast.tenant_id)
        .first()
    )
    channel_live = channel is not None and channel.is_active and not channel.is_trashed

    existing_ids = {
        row[0]
        for row in db.query(BroadcastRecipient.contact_id).filter(
            BroadcastRecipient.tenant_id == broadcast.tenant_id,
            BroadcastRecipient.broadcast_id == broadcast.id,
        )
    }

    identity_contact_ids: set = set()
    if channel_live:
        identity_contact_ids = {
            row[0]
            for row in db.query(ContactChannelIdentity.contact_id).filter(
                ContactChannelIdentity.tenant_id == broadcast.tenant_id,
                ContactChannelIdentity.channel_id == broadcast.channel_id,
            )
        }

    query = broadcast_audience_query(db, broadcast)

    skipped_by_reason: Dict[str, int] = {reason: 0 for reason in SKIP_REASONS}
    seen_this_call: set = set()
    batch: List[dict] = []

    def _flush() -> None:
        if batch:
            _bulk_insert_ignore(db, list(batch))
            batch.clear()

    for (contact_id,) in query.with_entities(Contact.id).yield_per(SNAPSHOT_BATCH_SIZE):
        if contact_id in existing_ids or contact_id in seen_this_call:
            skipped_by_reason["duplicate"] += 1
            continue
        seen_this_call.add(contact_id)

        # Every dict in the batch MUST carry the SAME key set - SQLAlchemy's
        # Core `insert().values([...])` compiles the multi-row VALUES clause
        # from the FIRST row's keys, so a `queued` row (no `skip_reason`)
        # mixed with a `skipped` row (has `skip_reason`) silently drops the
        # column for whichever rows didn't declare it (learned the hard way -
        # a `skipped/no_identity` row landed with `skip_reason=NULL`).
        if not channel_live:
            skipped_by_reason["channel_inactive"] += 1
            state, skip_reason = "skipped", "channel_inactive"
        elif contact_id not in identity_contact_ids:
            skipped_by_reason["no_identity"] += 1
            state, skip_reason = "skipped", "no_identity"
        else:
            state, skip_reason = "queued", None
        batch.append(
            dict(
                tenant_id=broadcast.tenant_id, broadcast_id=broadcast.id,
                contact_id=contact_id, state=state, skip_reason=skip_reason,
            )
        )

        if len(batch) >= SNAPSHOT_BATCH_SIZE:
            _flush()

    _flush()
    db.flush()
    recompute_counts(db, broadcast)
    return {"total": broadcast.total_count, "skippedByReason": skipped_by_reason}


def _bulk_insert_ignore(db: Session, rows: List[dict]) -> None:
    """Dialect-aware batched insert with ON CONFLICT DO NOTHING on the
    recipients' `UNIQUE(broadcast_id, contact_id)` - the idempotency backstop
    (D-A4-1) for a resumed/retried snapshot. Postgres in production, SQLite in
    the pytest suite (both dialects support `on_conflict_do_nothing`)."""
    table = BroadcastRecipient.__table__
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(table).values(rows).on_conflict_do_nothing(
            index_elements=["broadcast_id", "contact_id"]
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(table).values(rows).on_conflict_do_nothing(
            index_elements=["broadcast_id", "contact_id"]
        )
    else:  # pragma: no cover - defensive; only postgres/sqlite run this code
        stmt = table.insert().values(rows)
    db.execute(stmt)

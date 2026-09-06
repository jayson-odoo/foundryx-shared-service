"""The dashboard builder (plan 30, roadmap A9, slice S1) - `report()`'s seven
report builders land in slice S2 on top of the SAME `report_windows` /
`report_queries` / `report_stats` / `report_filters` core this module uses.

Every query here is tenant-scoped from the JWT AND workspace-scoped from the
path (never post-filtered in Python - AC-RPT-10), and every stored actor id
is resolved tenant-scoped in ONE batched pass (the `event_service._label_map`
pattern - AC-RPT-07) so a foreign/corrupt id can never render another
tenant's name.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace as _dc_replace
from datetime import timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, distinct, func, literal, or_
from sqlalchemy.orm import Session, aliased

from app.models.user import User

from ..models import Channel, CloseReason, Contact, ConversationEvent, ConversationMessage, WorkspaceMember
from ..models import Status as ThreadStatus
from ..schemas import (
    DashboardLifecycleStageItem,
    DashboardResponse,
    DashboardSeries,
    DashboardTiles,
    DashboardTopAgentItem,
    DurationStatsItem,
    ReportBucketItem,
    ReportDescriptorItem,
    ReportDimensionAvailability,
    ReportDimensions,
    ReportMetaResponse,
    ReportRange,
    ReportResponse,
    ReportSeriesItem,
)
from . import report_queries, report_stats
from .lifecycle_service import stages_for_workspace
from .report_filters import ReportQuery, build_query, team_available
from .report_windows import GRANULARITIES

# The seven-report catalog (`reports/meta`, S2 fills the `/reports/{key}`
# builders themselves) - the ONE list `groupBy` validation (S2) and the
# frontend picker both read, never forked (AC-RPT-17/29).
REPORT_DESCRIPTORS: List[ReportDescriptorItem] = [
    ReportDescriptorItem(key="conversations", label="Conversations", supportsGroupBy=[], paginated=False, exportable=True),
    ReportDescriptorItem(key="responses", label="Responses", supportsGroupBy=["user"], paginated=False, exportable=True),
    ReportDescriptorItem(key="resolutions", label="Resolutions", supportsGroupBy=["user"], paginated=False, exportable=True),
    ReportDescriptorItem(key="messages", label="Messages", supportsGroupBy=["channel"], paginated=False, exportable=True),
    ReportDescriptorItem(key="users", label="Users", supportsGroupBy=[], paginated=True, exportable=True),
    ReportDescriptorItem(key="leaderboard", label="Leaderboard", supportsGroupBy=[], paginated=True, exportable=True),
    ReportDescriptorItem(key="assignments", label="Assignment log", supportsGroupBy=[], paginated=True, exportable=True),
]


REPORT_KEYS = {d.key for d in REPORT_DESCRIPTORS}
_DESCRIPTOR_BY_KEY = {d.key: d for d in REPORT_DESCRIPTORS}

# Reports that read the WORKSPACE'S channel dimension at all - `messages` is
# the only report that carries a channel column (`conversation_messages.
# channel_id`); `conversation_events` has none. `channelId` is still validated
# (workspace-scoped) for every report by `report_filters.build_query`, but for
# every OTHER report it is accepted and simply has no filtering effect rather
# than misrepresenting history through the contact's CURRENT channel identity
# (AC-RPT-30, S1 handoff decision - documented here since `reports/meta`'s
# wire shape is already pinned by the S0 frontend contract and does not carry
# a per-report `supportsFilters` list).
CHANNEL_FILTERED_REPORTS = {"messages"}


class ReportKeyNotFound(Exception):
    """422/404-worthy - the router maps this to a uniform 404 (AC-RPT-29)."""


class GroupByNotSupported(Exception):
    """AC-RPT-29 - `groupBy` is not in the report's own `supportsGroupBy`."""

    def __init__(self, report_key: str, allowed: List[str]):
        self.report_key = report_key
        self.allowed = allowed
        super().__init__(f"{report_key} does not support groupBy; allowed: {allowed}")


def descriptor_for(report_key: str) -> ReportDescriptorItem:
    descriptor = _DESCRIPTOR_BY_KEY.get(report_key)
    if descriptor is None:
        raise ReportKeyNotFound(report_key)
    return descriptor


def reports_meta() -> ReportMetaResponse:
    """AC-RPT-17 (meta half) - static catalog data, no DB access."""
    return ReportMetaResponse(
        reports=REPORT_DESCRIPTORS,
        granularities=list(GRANULARITIES),
        dimensions=ReportDimensions(team=ReportDimensionAvailability(available=team_available())),
    )


class ResponseSample:
    __slots__ = ("contact_id", "seconds", "actor_user_id", "derived")

    def __init__(self, contact_id: str, seconds: int, actor_user_id: Optional[str], derived: bool):
        self.contact_id = contact_id
        self.seconds = seconds
        self.actor_user_id = actor_user_id
        self.derived = derived


class ResolutionSample:
    __slots__ = ("contact_id", "seconds", "actor_user_id", "close_reason_id")

    def __init__(
        self, contact_id: str, seconds: int, actor_user_id: Optional[str], close_reason_id: Optional[str]
    ):
        self.contact_id = contact_id
        self.seconds = seconds
        self.actor_user_id = actor_user_id
        self.close_reason_id = close_reason_id


def _event_filters(rq: ReportQuery, event_type: Optional[str] = None) -> list:
    filters = [
        ConversationEvent.tenant_id == rq.tenant_id,
        ConversationEvent.workspace_id == rq.workspace_id,
    ]
    if event_type is not None:
        filters.append(ConversationEvent.event_type == event_type)
    return filters


def response_samples(db: Session, rq: ReportQuery) -> List[ResponseSample]:
    """Primary source = `first_agent_reply` events in the window
    (`payload_json.responseSeconds`); legacy source (D-A9-6) = for a contact
    with NO `first_agent_reply` event AT ALL, the first `AGENT` message minus
    the latest `CONTACT` message strictly before it - a `SYSTEM` note never
    counts as a reply, and a contact already carrying an event contributes
    only its event value (AC-RPT-06)."""
    filters = _event_filters(rq, "first_agent_reply")
    filters += [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
    ]
    if rq.user_id:
        filters.append(ConversationEvent.actor_user_id == rq.user_id)

    query = db.query(
        ConversationEvent.contact_id, ConversationEvent.actor_user_id, ConversationEvent.payload_json
    ).filter(*filters)
    rows = report_queries.duration_samples(query, cap=report_queries.REPORT_MAX_SAMPLE_ROWS)

    samples: List[ResponseSample] = [
        ResponseSample(
            contact_id=contact_id,
            seconds=int((payload or {}).get("responseSeconds") or 0),
            actor_user_id=actor_user_id,
            derived=False,
        )
        for contact_id, actor_user_id, payload in rows
    ]

    # D-A9-6: contacts with NO `first_agent_reply` event at all, anywhere in
    # their history (not just this window) - a genuinely legacy thread.
    no_reply_query = db.query(Contact.id).filter(
        Contact.tenant_id == rq.tenant_id,
        Contact.workspace_id == rq.workspace_id,
        ~db.query(ConversationEvent.id)
        .filter(
            ConversationEvent.contact_id == Contact.id,
            ConversationEvent.event_type == "first_agent_reply",
        )
        .exists(),
    )
    no_reply_ids = [
        r[0]
        for r in report_queries.duration_samples(
            no_reply_query, cap=report_queries.REPORT_MAX_SAMPLE_ROWS
        )
    ]

    if no_reply_ids:
        messages = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == rq.tenant_id,
                ConversationMessage.contact_id.in_(no_reply_ids),
                ConversationMessage.sender_type.in_(("AGENT", "CONTACT")),
            )
            .order_by(ConversationMessage.contact_id, ConversationMessage.created_at, ConversationMessage.id)
            .all()
        )
        by_contact: Dict[str, list] = defaultdict(list)
        for m in messages:
            by_contact[m.contact_id].append(m)
        for contact_id, msgs in by_contact.items():
            last_contact_before = None
            first_agent = None
            for m in msgs:
                if m.sender_type == "AGENT":
                    first_agent = m
                    break
                last_contact_before = m
            if first_agent is None or last_contact_before is None:
                continue
            if not (rq.window_start <= first_agent.created_at < rq.window_end):
                continue
            if rq.user_id and first_agent.sender_id != rq.user_id:
                continue
            seconds = int((first_agent.created_at - last_contact_before.created_at).total_seconds())
            samples.append(
                ResponseSample(
                    contact_id=contact_id, seconds=seconds, actor_user_id=first_agent.sender_id, derived=True
                )
            )
    return samples


def resolution_samples(db: Session, rq: ReportQuery) -> List[ResolutionSample]:
    """Each `closed` event pairs with the LATEST `opened`/`reopened` event of
    the SAME contact at or before it - a portable correlated scalar subquery
    (dialect-free, D-A9-8/9), never a per-row Python loop over the whole
    table. A `closed` event with no preceding cycle-start event contributes
    nothing (AC-RPT-22)."""
    filters = _event_filters(rq, "closed")
    filters += [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
    ]
    if rq.user_id:
        filters.append(ConversationEvent.actor_user_id == rq.user_id)

    cycle_marker = aliased(ConversationEvent)
    cycle_start_at = (
        db.query(func.max(cycle_marker.created_at))
        .filter(
            cycle_marker.contact_id == ConversationEvent.contact_id,
            cycle_marker.event_type.in_(("opened", "reopened")),
            cycle_marker.created_at <= ConversationEvent.created_at,
        )
        .correlate(ConversationEvent)
        .scalar_subquery()
    )

    query = db.query(
        ConversationEvent.contact_id,
        ConversationEvent.actor_user_id,
        ConversationEvent.close_reason_id,
        ConversationEvent.created_at,
        cycle_start_at.label("cycle_start_at"),
    ).filter(*filters)
    rows = report_queries.duration_samples(query, cap=report_queries.REPORT_MAX_SAMPLE_ROWS)

    samples: List[ResolutionSample] = []
    for contact_id, actor_user_id, close_reason_id, closed_at, cycle_start in rows:
        if cycle_start is None:
            continue
        seconds = int((closed_at - cycle_start).total_seconds())
        samples.append(
            ResolutionSample(
                contact_id=contact_id, seconds=seconds, actor_user_id=actor_user_id, close_reason_id=close_reason_id
            )
        )
    return samples


def _tiles(db: Session, rq: ReportQuery) -> DashboardTiles:
    """CURRENT STATE only - ignores `from`/`to` entirely (AC-RPT-01). A
    `userId` filter scopes to threads CURRENTLY assigned to that user (every
    tile, AC-RPT-09), which makes `unassigned` naturally 0 in that case."""
    filters = [Contact.tenant_id == rq.tenant_id, Contact.workspace_id == rq.workspace_id]
    if rq.user_id:
        filters.append(Contact.assigned_user_id == rq.user_id)

    key_expr = func.coalesce(ThreadStatus.key, literal("OPEN"))
    not_closed = key_expr != "CLOSED"
    has_assignee = or_(Contact.assigned_user_id.isnot(None), Contact.assigned_external_agent_id.isnot(None))

    row = (
        db.query(
            func.sum(case((key_expr == "OPEN", 1), else_=0)),
            func.sum(case((key_expr == "SNOOZED", 1), else_=0)),
            func.sum(case((and_(not_closed, has_assignee), 1), else_=0)),
            func.sum(case((and_(not_closed, ~has_assignee), 1), else_=0)),
        )
        .select_from(Contact)
        .outerjoin(ThreadStatus, ThreadStatus.id == Contact.status_id)
        .filter(*filters)
        .one()
    )
    open_count, snoozed_count, assigned_count, unassigned_count = (int(v or 0) for v in row)
    return DashboardTiles(
        open=open_count, assigned=assigned_count, unassigned=unassigned_count, snoozed=snoozed_count
    )


def _lifecycle(db: Session, rq: ReportQuery) -> List[DashboardLifecycleStageItem]:
    """CURRENT STATE, workspace-wide (AC-RPT-02) - a stage with zero contacts
    is still listed, never dropped."""
    stages = stages_for_workspace(db, rq.tenant_id, rq.workspace_id)
    counts = dict(
        db.query(Contact.lifecycle_status_id, func.count())
        .filter(
            Contact.tenant_id == rq.tenant_id,
            Contact.workspace_id == rq.workspace_id,
            Contact.lifecycle_status_id.isnot(None),
        )
        .group_by(Contact.lifecycle_status_id)
        .all()
    )
    total = sum(counts.values())
    items = []
    for stage in stages:
        count = counts.get(stage.id, 0)
        percent = round(count / total * 100, 1) if total else 0.0
        items.append(
            DashboardLifecycleStageItem(
                statusId=stage.id,
                key=stage.key,
                label=stage.label,
                color=stage.color,
                sortOrder=stage.sort_order,
                count=count,
                percent=percent,
            )
        )
    return items


def _series(db: Session, rq: ReportQuery) -> DashboardSeries:
    filters = [ConversationEvent.tenant_id == rq.tenant_id, ConversationEvent.workspace_id == rq.workspace_id]
    if rq.user_id:
        filters.append(ConversationEvent.actor_user_id == rq.user_id)
    series_predicates = {
        "opened": ConversationEvent.event_type == "opened",
        "closed": ConversationEvent.event_type == "closed",
    }
    counts = report_queries.bucketed_counts(
        db, ConversationEvent.created_at, filters, rq.buckets, series_predicates
    )
    return DashboardSeries(opened=counts["opened"], closed=counts["closed"])


def _top_agents(db: Session, rq: ReportQuery, samples: List[ResponseSample]) -> List[DashboardTopAgentItem]:
    filters = _event_filters(rq, "closed")
    filters += [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
        ConversationEvent.actor_user_id.isnot(None),
    ]
    if rq.user_id:
        filters.append(ConversationEvent.actor_user_id == rq.user_id)
    closed_counts = dict(
        db.query(ConversationEvent.actor_user_id, func.count())
        .filter(*filters)
        .group_by(ConversationEvent.actor_user_id)
        .all()
    )
    if not closed_counts:
        return []

    # Tenant-scoped, batched (AC-RPT-07) - an unresolvable/foreign id renders
    # an empty name, never another tenant's user (the polymorphic stored-id
    # house rule).
    names = {
        u.id: (u.name or u.email)
        for u in db.query(User).filter(User.tenant_id == rq.tenant_id, User.id.in_(closed_counts)).all()
    }

    by_agent: Dict[str, List[int]] = defaultdict(list)
    for s in samples:
        if s.actor_user_id:
            by_agent[s.actor_user_id].append(s.seconds)

    agents = [
        DashboardTopAgentItem(
            userId=user_id,
            name=names.get(user_id, ""),
            closedCount=closed_count,
            medianResponseSeconds=report_stats.median(sorted(by_agent.get(user_id, []))),
        )
        for user_id, closed_count in closed_counts.items()
    ]
    agents.sort(key=lambda a: (-a.closedCount, a.name))
    return agents


def dashboard(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    from_: str,
    to: str,
    tz: str,
    granularity: Optional[str] = None,
    user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    team_id: Optional[str] = None,
) -> DashboardResponse:
    """The dashboard payload (plan §5.2). Raises `ReportValidationError`
    (422 `{fieldErrors}`) or `SampleCapExceeded` (422) - the router maps
    both."""
    rq = build_query(
        db,
        tenant_id,
        workspace_id,
        from_=from_,
        to=to,
        tz=tz,
        granularity=granularity,
        user_id=user_id,
        channel_id=channel_id,
        team_id=team_id,
    )

    resp_samples = response_samples(db, rq)
    resol_samples = resolution_samples(db, rq)

    response_stats = report_stats.stats_of([s.seconds for s in resp_samples])
    derived_count = sum(1 for s in resp_samples if s.derived)
    resolution_stats = report_stats.stats_of([s.seconds for s in resol_samples])

    return DashboardResponse(
        timezone=rq.tz_name,
        range=ReportRange(**{"from": from_, "to": to}),
        granularity=rq.granularity,
        buckets=[ReportBucketItem(key=b.key, startsAt=b.starts_at, endsAt=b.ends_at) for b in rq.buckets],
        tiles=_tiles(db, rq),
        lifecycle=_lifecycle(db, rq),
        series=_series(db, rq),
        responseTotals=DurationStatsItem(**response_stats, derivedFromMessages=derived_count),
        resolutionTotals=DurationStatsItem(**resolution_stats),
        topAgents=_top_agents(db, rq, resp_samples),
    )


# ── Slice S2 - the seven report builders + the assignment log ───────────────
# Every builder returns the ONE `ReportResponse` envelope (plan §5.2). No
# report builds SQL from a client string - every identifier below is a
# server-side model column or constant (AC-RPT-32); `Contact`/`Channel`/
# `CloseReason`/`stages_for_workspace` are reused unchanged from S1, never
# forked into a second column map.


def _iso_z(value) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _envelope(
    rq: ReportQuery,
    report_key: str,
    *,
    series: List[ReportSeriesItem],
    rows: List[Dict[str, Any]],
    totals: Dict[str, Any],
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    total: Optional[int] = None,
) -> ReportResponse:
    return ReportResponse(
        reportKey=report_key,
        timezone=rq.tz_name,
        range=ReportRange(**{"from": rq.from_str, "to": rq.to_str}),
        granularity=rq.granularity,
        buckets=[ReportBucketItem(key=b.key, startsAt=b.starts_at, endsAt=b.ends_at) for b in rq.buckets],
        series=series,
        rows=rows,
        totals=totals,
        page=page,
        pageSize=page_size,
        total=total,
    )


def _workspace_member_users(db: Session, tenant_id: str, workspace_id: str) -> List[User]:
    users = (
        db.query(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(
            WorkspaceMember.tenant_id == tenant_id,
            WorkspaceMember.workspace_id == workspace_id,
            User.tenant_id == tenant_id,
        )
        .all()
    )
    users.sort(key=lambda u: ((u.name or u.email or "").lower(), u.id))
    return users


def _event_filters_multi(rq: ReportQuery, event_types: tuple) -> list:
    filters = [
        ConversationEvent.tenant_id == rq.tenant_id,
        ConversationEvent.workspace_id == rq.workspace_id,
        ConversationEvent.event_type.in_(event_types),
    ]
    return filters


# ── conversations ────────────────────────────────────────────────────────────
def _report_conversations(db: Session, rq: ReportQuery) -> ReportResponse:
    # The window bound is redundant with the per-bucket CASE predicates below
    # (the buckets collectively cover exactly this window) but lets Postgres
    # use `ix_conv_events_ws_created (tenant_id, workspace_id, created_at)`
    # as a genuine range scan instead of reading the workspace's whole event
    # history on every call - same reasoning as `_message_filters` (D-A9-12).
    filters = _event_filters(rq) + [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
    ]
    if rq.user_id:
        filters.append(ConversationEvent.actor_user_id == rq.user_id)
    series_predicates = {
        "opened": ConversationEvent.event_type == "opened",
        "closed": ConversationEvent.event_type == "closed",
        "reopened": ConversationEvent.event_type == "reopened",
    }
    counts = report_queries.bucketed_counts(
        db, ConversationEvent.created_at, filters, rq.buckets, series_predicates
    )
    series = [
        ReportSeriesItem(key="opened", label="Opened", points=counts["opened"]),
        ReportSeriesItem(key="closed", label="Closed", points=counts["closed"]),
        ReportSeriesItem(key="reopened", label="Reopened", points=counts["reopened"]),
    ]
    totals = {
        "opened": sum(counts["opened"]),
        "closed": sum(counts["closed"]),
        "reopened": sum(counts["reopened"]),
    }
    return _envelope(rq, "conversations", series=series, rows=[], totals=totals)


# ── responses / resolutions shared per-user breakdown ────────────────────────
def _duration_by_user_rows(db: Session, rq: ReportQuery, samples: list) -> List[Dict[str, Any]]:
    members = _workspace_member_users(db, rq.tenant_id, rq.workspace_id)
    by_user: Dict[str, List[int]] = defaultdict(list)
    for s in samples:
        if s.actor_user_id:
            by_user[s.actor_user_id].append(s.seconds)
    rows: List[Dict[str, Any]] = []
    for u in members:
        values = sorted(by_user.get(u.id, []))
        rows.append(
            {
                "userId": u.id,
                "name": u.name or u.email,
                "sampleCount": len(values),
                "medianSeconds": report_stats.median(values),
                "p90Seconds": report_stats.percentile(values, 0.9),
                "averageSeconds": report_stats.average(values),
            }
        )
    return rows


def _report_responses(db: Session, rq: ReportQuery) -> ReportResponse:
    samples = response_samples(db, rq)
    values = [s.seconds for s in samples]
    stats = report_stats.stats_of(values)
    derived_count = sum(1 for s in samples if s.derived)
    totals = {**stats, "derivedFromMessages": derived_count}
    if rq.group_by == "user":
        rows = _duration_by_user_rows(db, rq, samples)
    else:
        rows = report_stats.bucket_distribution(values)
    return _envelope(rq, "responses", series=[], rows=rows, totals=totals)


def _close_reason_rows(db: Session, rq: ReportQuery, samples: list) -> List[Dict[str, Any]]:
    """Ordered by `CloseReason.sort_order` (the workspace's own configured
    order, AC-RPT-21) - never invented alphabetically. A `close_reason_id` of
    NULL (or, defense-in-depth, one this workspace no longer owns) renders an
    empty `name`, appended last, never dropped (AC-RPT-21)."""
    total = len(samples)
    counts: Dict[Optional[str], int] = defaultdict(int)
    for s in samples:
        counts[s.close_reason_id] += 1

    reason_ids = [rid for rid in counts if rid]
    reasons = []
    if reason_ids:
        reasons = (
            db.query(CloseReason)
            .filter(
                CloseReason.tenant_id == rq.tenant_id,
                CloseReason.workspace_id == rq.workspace_id,
                CloseReason.id.in_(reason_ids),
            )
            .order_by(CloseReason.sort_order.asc(), func.lower(CloseReason.name).asc())
            .all()
        )

    rows: List[Dict[str, Any]] = []
    for r in reasons:
        count = counts.pop(r.id, 0)
        percent = round(count / total * 100, 1) if total else 0.0
        rows.append({"closeReasonId": r.id, "name": r.name, "count": count, "percent": percent})
    # The NULL group plus any id this workspace can't resolve (should never
    # happen - defense-in-depth, the polymorphic stored-id house rule).
    for reason_id, count in counts.items():
        percent = round(count / total * 100, 1) if total else 0.0
        rows.append({"closeReasonId": reason_id, "name": None, "count": count, "percent": percent})
    return rows


def _report_resolutions(db: Session, rq: ReportQuery) -> ReportResponse:
    samples = resolution_samples(db, rq)
    values = [s.seconds for s in samples]
    stats = report_stats.stats_of(values)
    if rq.group_by == "user":
        rows = _duration_by_user_rows(db, rq, samples)
    else:
        rows = _close_reason_rows(db, rq, samples)
    return _envelope(rq, "resolutions", series=[], rows=rows, totals=stats)


# ── messages ─────────────────────────────────────────────────────────────────
def _message_filters(rq: ReportQuery) -> list:
    """Joins `Contact` for workspace scoping (`ConversationMessage` itself
    carries no `workspace_id` - D-A9-12) via an implicit-join predicate.

    Includes the window bound (`created_at` in `[window_start, window_end)`)
    even though `bucketed_counts`' per-bucket `CASE`s already restrict what
    gets SUMMED - the buckets collectively cover exactly this window, so the
    bound changes no result, only whether Postgres can use a `(tenant_id,
    created_at)` index to avoid scanning the workspace's ENTIRE message
    history on every call (D-A9-12's whole concern - see the index
    measurement in this module's docstring / the plan's S2 handoff)."""
    filters = [
        ConversationMessage.tenant_id == rq.tenant_id,
        ConversationMessage.created_at >= rq.window_start,
        ConversationMessage.created_at < rq.window_end,
        Contact.id == ConversationMessage.contact_id,
        Contact.tenant_id == rq.tenant_id,
        Contact.workspace_id == rq.workspace_id,
    ]
    if rq.channel_id:
        filters.append(ConversationMessage.channel_id == rq.channel_id)
    if rq.user_id:
        # Messages have no "assignee" - the only actor a message carries is
        # its own sender (S2 documented simplification: a `userId` filter on
        # `messages` scopes to that agent's OWN outgoing messages, so the
        # incoming series naturally reads 0 - no numeric AC pins this combo).
        filters.append(ConversationMessage.sender_id == rq.user_id)
    return filters


def _messages_by_channel_rows(db: Session, rq: ReportQuery) -> List[Dict[str, Any]]:
    filters = _message_filters(rq)
    rows_data = (
        db.query(
            ConversationMessage.channel_id,
            func.sum(case((ConversationMessage.sender_type == "CONTACT", 1), else_=0)),
            func.sum(case((ConversationMessage.sender_type == "AGENT", 1), else_=0)),
        )
        .filter(*filters)
        .group_by(ConversationMessage.channel_id)
        .all()
    )
    channel_ids = [r[0] for r in rows_data if r[0]]
    channels: Dict[str, Channel] = {}
    if channel_ids:
        for ch in (
            db.query(Channel)
            .filter(
                Channel.tenant_id == rq.tenant_id,
                Channel.workspace_id == rq.workspace_id,
                Channel.id.in_(channel_ids),
            )
            .all()
        ):
            channels[ch.id] = ch

    rows: List[Dict[str, Any]] = []
    for channel_id, incoming, outgoing in rows_data:
        if channel_id is None:
            continue  # a SYSTEM note carries no channel - never a row here
        ch = channels.get(channel_id)
        rows.append(
            {
                "channelId": channel_id,
                "name": ch.name if ch else "",
                "channelType": ch.channel_type if ch else "WHATSAPP",
                "incoming": int(incoming or 0),
                "outgoing": int(outgoing or 0),
            }
        )
    rows.sort(key=lambda r: (r["name"], r["channelId"]))
    return rows


def _report_messages(db: Session, rq: ReportQuery) -> ReportResponse:
    filters = _message_filters(rq)
    series_predicates = {
        "incoming": ConversationMessage.sender_type == "CONTACT",
        "outgoing": ConversationMessage.sender_type == "AGENT",
    }
    counts = report_queries.bucketed_counts(
        db, ConversationMessage.created_at, filters, rq.buckets, series_predicates
    )
    series = [
        ReportSeriesItem(key="incoming", label="Incoming", points=counts["incoming"]),
        ReportSeriesItem(key="outgoing", label="Outgoing", points=counts["outgoing"]),
    ]
    totals = {"incoming": sum(counts["incoming"]), "outgoing": sum(counts["outgoing"])}
    rows: List[Dict[str, Any]] = []
    if rq.group_by == "channel":
        rows = _messages_by_channel_rows(db, rq)
    return _envelope(rq, "messages", series=series, rows=rows, totals=totals)


# ── users / leaderboard ───────────────────────────────────────────────────────
def _build_user_rows(db: Session, rq: ReportQuery) -> List[Dict[str, Any]]:
    """`users`/`leaderboard` always compare EVERY member - a `userId` filter
    would collapse the comparison to a single row, which defeats the report's
    purpose (respond.io's own Users/Leaderboard reports ignore a user filter
    the same way); `_dc_replace` clears it for the per-user stats reused from
    S1 without mutating the caller's `rq` (still used for the envelope's
    echoed `range`/`timezone`/etc.)."""
    members = _workspace_member_users(db, rq.tenant_id, rq.workspace_id)
    stats_rq = _dc_replace(rq, user_id=None)
    resp_samples = response_samples(db, stats_rq)
    resol_samples = resolution_samples(db, stats_rq)

    assigned_filters = _event_filters(rq, "assigned") + [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
        ConversationEvent.to_value.isnot(None),
    ]
    assigned_counts = dict(
        db.query(ConversationEvent.to_value, func.count())
        .filter(*assigned_filters)
        .group_by(ConversationEvent.to_value)
        .all()
    )

    closed_filters = _event_filters(rq, "closed") + [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
        ConversationEvent.actor_user_id.isnot(None),
    ]
    closed_counts = dict(
        db.query(ConversationEvent.actor_user_id, func.count())
        .filter(*closed_filters)
        .group_by(ConversationEvent.actor_user_id)
        .all()
    )

    comment_filters = _event_filters(rq, "comment_added") + [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
        ConversationEvent.actor_user_id.isnot(None),
    ]
    comment_counts = dict(
        db.query(ConversationEvent.actor_user_id, func.count())
        .filter(*comment_filters)
        .group_by(ConversationEvent.actor_user_id)
        .all()
    )

    msg_filters = [
        ConversationMessage.tenant_id == rq.tenant_id,
        Contact.id == ConversationMessage.contact_id,
        Contact.tenant_id == rq.tenant_id,
        Contact.workspace_id == rq.workspace_id,
        ConversationMessage.sender_type == "AGENT",
        ConversationMessage.sender_id.isnot(None),
        ConversationMessage.created_at >= rq.window_start,
        ConversationMessage.created_at < rq.window_end,
    ]
    msg_rows = (
        db.query(
            ConversationMessage.sender_id,
            func.count(),
            func.count(distinct(ConversationMessage.contact_id)),
        )
        .filter(*msg_filters)
        .group_by(ConversationMessage.sender_id)
        .all()
    )
    messages_sent = {r[0]: r[1] for r in msg_rows}
    unique_contacts = {r[0]: r[2] for r in msg_rows}

    by_response: Dict[str, List[int]] = defaultdict(list)
    for s in resp_samples:
        if s.actor_user_id:
            by_response[s.actor_user_id].append(s.seconds)
    by_resolution: Dict[str, List[int]] = defaultdict(list)
    for s in resol_samples:
        if s.actor_user_id:
            by_resolution[s.actor_user_id].append(s.seconds)

    rows: List[Dict[str, Any]] = []
    for u in members:
        rows.append(
            {
                "userId": u.id,
                "name": u.name or u.email,
                "teamName": None,  # D-A9-13 - null until plan 28/A8 lands
                "assignedCount": int(assigned_counts.get(u.id, 0) or 0),
                "closedCount": int(closed_counts.get(u.id, 0) or 0),
                "uniqueContacts": int(unique_contacts.get(u.id, 0) or 0),
                "messagesSent": int(messages_sent.get(u.id, 0) or 0),
                "commentsCount": int(comment_counts.get(u.id, 0) or 0),
                "medianFirstResponseSeconds": report_stats.median(sorted(by_response.get(u.id, []))),
                "medianResolutionSeconds": report_stats.median(sorted(by_resolution.get(u.id, []))),
            }
        )
    return rows


def _paginate(rows: List[Dict[str, Any]], page: int, page_size: int) -> tuple:
    total = len(rows)
    start = page * page_size
    return rows[start : start + page_size], total


def _report_users(db: Session, rq: ReportQuery, page: int, page_size: int) -> ReportResponse:
    all_rows = _build_user_rows(db, rq)
    all_rows.sort(key=lambda r: (r["name"].lower(), r["userId"]))
    page_rows, total = _paginate(all_rows, page, page_size)
    totals = {"userCount": total}
    return _envelope(
        rq, "users", series=[], rows=page_rows, totals=totals, page=page, page_size=page_size, total=total
    )


def _report_leaderboard(db: Session, rq: ReportQuery, page: int, page_size: int) -> ReportResponse:
    """AC-RPT-25: `closedCount` desc, `medianFirstResponseSeconds` asc (nulls
    last), name asc - `userId` asc is the FINAL tiebreak underneath "name asc"
    (AC-RPT-28's determinism guarantee: two members could share a display
    name, `userId` never collides)."""
    all_rows = _build_user_rows(db, rq)
    all_rows.sort(
        key=lambda r: (
            -r["closedCount"],
            r["medianFirstResponseSeconds"] if r["medianFirstResponseSeconds"] is not None else float("inf"),
            r["name"].lower(),
            r["userId"],
        )
    )
    for i, row in enumerate(all_rows, start=1):
        row["rank"] = i
    page_rows, total = _paginate(all_rows, page, page_size)
    totals = {"userCount": total}
    return _envelope(
        rq, "leaderboard", series=[], rows=page_rows, totals=totals, page=page, page_size=page_size, total=total
    )


# ── assignments (the assignment log) ─────────────────────────────────────────
def _assignee_label_map(db: Session, tenant_id: str, ids: set) -> Dict[str, str]:
    """The assignment log's `from_value`/`to_value` are ALWAYS an assignee id
    (a native user or an external agent, per `assigneeKind` - never a status
    id), so this is a narrower sibling of `event_service._label_map`'s
    pattern: ONE batched, tenant-scoped pass, an unresolvable id renders an
    empty name, never another tenant's (the polymorphic stored-id rule)."""
    if not ids:
        return {}
    labels: Dict[str, str] = {}
    for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all():
        labels[u.id] = u.name or u.email
    remaining = ids - set(labels)
    if remaining:
        from .external_agent_service import ExternalAgentService

        for agent_id, agent in ExternalAgentService(db).names(list(remaining), tenant_id).items():
            labels[agent_id] = agent.name
    return labels


def _assignment_log_rows(
    db: Session, tenant_id: str, workspace_id: str, events: List[ConversationEvent]
) -> List[Dict[str, Any]]:
    contact_ids = {e.contact_id for e in events}
    contact_names: Dict[str, str] = {}
    if contact_ids:
        for c in (
            db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id, Contact.id.in_(contact_ids))
            .all()
        ):
            name = " ".join(p for p in (c.first_name, c.last_name) if p) or c.phone or ""
            contact_names[c.id] = name

    assignee_ids: set = set()
    for e in events:
        if e.from_value:
            assignee_ids.add(e.from_value)
        if e.to_value:
            assignee_ids.add(e.to_value)
    assignee_labels = _assignee_label_map(db, tenant_id, assignee_ids)

    actor_user_ids = {e.actor_user_id for e in events if e.actor_user_id}
    actor_names: Dict[str, str] = {}
    if actor_user_ids:
        for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(actor_user_ids)).all():
            actor_names[u.id] = u.name or u.email
    actor_external_ids = {e.actor_external_agent_id for e in events if e.actor_external_agent_id}
    if actor_external_ids:
        from .external_agent_service import ExternalAgentService

        for agent_id, agent in ExternalAgentService(db).names(list(actor_external_ids), tenant_id).items():
            actor_names[agent_id] = agent.name

    rows: List[Dict[str, Any]] = []
    for e in events:
        payload = e.payload_json or {}
        # AC-RPT-27: `workflow` when the writer said so explicitly, `api`
        # when no actor of any kind wrote it (today the ONLY such caller is
        # the public gateway - `ConversationService.patch_thread(actor=None)`
        # - a system/backfill event never reaches this log since it is never
        # `assigned`/`unassigned`), otherwise `agent`.
        if payload.get("source") == "workflow":
            source = "workflow"
        elif e.actor_user_id is None and e.actor_external_agent_id is None:
            source = "api"
        else:
            source = "agent"

        if e.actor_external_agent_id:
            actor_name = actor_names.get(e.actor_external_agent_id)
        elif e.actor_user_id:
            actor_name = actor_names.get(e.actor_user_id)
        else:
            actor_name = None

        rows.append(
            {
                "id": e.id,
                "createdAt": _iso_z(e.created_at),
                "contactId": e.contact_id,
                "contactName": contact_names.get(e.contact_id, ""),
                "eventType": e.event_type,
                "previousAssigneeId": e.from_value,
                "previousAssigneeName": assignee_labels.get(e.from_value) if e.from_value else None,
                "assignedToId": e.to_value,
                "assignedToName": assignee_labels.get(e.to_value) if e.to_value else None,
                "source": source,
                "actorUserId": e.actor_user_id,
                "actorName": actor_name,
            }
        )
    return rows


def _report_assignments(db: Session, rq: ReportQuery, page: int, page_size: int) -> ReportResponse:
    base_filters = _event_filters_multi(rq, ("assigned", "unassigned"))
    if rq.user_id:
        base_filters.append(or_(ConversationEvent.actor_user_id == rq.user_id, ConversationEvent.to_value == rq.user_id))
    # Same D-A9-12 reasoning as `_message_filters`/`_report_conversations` -
    # redundant with the bucket CASEs, lets the index do a range scan.
    window_filters = base_filters + [
        ConversationEvent.created_at >= rq.window_start,
        ConversationEvent.created_at < rq.window_end,
    ]

    series_predicates = {"assigned": ConversationEvent.event_type == "assigned"}
    counts = report_queries.bucketed_counts(
        db, ConversationEvent.created_at, window_filters, rq.buckets, series_predicates
    )
    series = [ReportSeriesItem(key="assigned", label="Assigned", points=counts["assigned"])]

    totals_row = (
        db.query(
            func.sum(case((ConversationEvent.event_type == "assigned", 1), else_=0)),
            func.sum(case((ConversationEvent.event_type == "unassigned", 1), else_=0)),
        )
        .filter(*window_filters)
        .one()
    )
    totals = {"assigned": int(totals_row[0] or 0), "unassigned": int(totals_row[1] or 0)}

    total_count = db.query(func.count(ConversationEvent.id)).filter(*window_filters).scalar() or 0
    events = (
        db.query(ConversationEvent)
        .filter(*window_filters)
        .order_by(ConversationEvent.created_at.desc(), ConversationEvent.id.desc())
        .offset(page * page_size)
        .limit(page_size)
        .all()
    )
    rows = _assignment_log_rows(db, rq.tenant_id, rq.workspace_id, events)
    return _envelope(
        rq,
        "assignments",
        series=series,
        rows=rows,
        totals=totals,
        page=page,
        page_size=page_size,
        total=int(total_count),
    )


_PAGINATED_BUILDERS = {
    "users": _report_users,
    "leaderboard": _report_leaderboard,
    "assignments": _report_assignments,
}
_UNPAGINATED_BUILDERS = {
    "conversations": _report_conversations,
    "responses": _report_responses,
    "resolutions": _report_resolutions,
    "messages": _report_messages,
}

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25


def report(
    db: Session,
    report_key: str,
    *,
    tenant_id: str,
    workspace_id: str,
    from_: str,
    to: str,
    tz: str,
    granularity: Optional[str] = None,
    user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    team_id: Optional[str] = None,
    group_by: Optional[str] = None,
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> ReportResponse:
    """AC-RPT-17..32. Raises `ReportKeyNotFound` (router -> uniform 404),
    `GroupByNotSupported` / `ReportValidationError` (router -> 422
    `{fieldErrors}`) or `SampleCapExceeded` (422)."""
    descriptor = descriptor_for(report_key)
    if group_by is not None and group_by not in descriptor.supportsGroupBy:
        raise GroupByNotSupported(report_key, descriptor.supportsGroupBy)

    # AC-RPT-30: `channelId` is validated (workspace-scoped) for every report
    # by `build_query`, but only APPLIED in SQL for message-based reports -
    # never silently misrepresented through an unrelated dimension. Pass the
    # real `channel_id` through `build_query` regardless (so a bad id is
    # still 422 either way); the non-message builders simply never read
    # `rq.channel_id`.
    rq = build_query(
        db,
        tenant_id,
        workspace_id,
        from_=from_,
        to=to,
        tz=tz,
        granularity=granularity,
        user_id=user_id,
        channel_id=channel_id,
        group_by=group_by,
        team_id=team_id,
    )
    if report_key not in CHANNEL_FILTERED_REPORTS:
        rq.channel_id = None

    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(0, page)

    if report_key in _PAGINATED_BUILDERS:
        return _PAGINATED_BUILDERS[report_key](db, rq, page, page_size)
    return _UNPAGINATED_BUILDERS[report_key](db, rq)

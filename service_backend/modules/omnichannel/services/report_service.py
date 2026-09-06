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
from typing import Dict, List, Optional

from sqlalchemy import and_, case, func, literal, or_
from sqlalchemy.orm import Session, aliased

from app.models.user import User

from ..models import Contact, ConversationEvent, ConversationMessage
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

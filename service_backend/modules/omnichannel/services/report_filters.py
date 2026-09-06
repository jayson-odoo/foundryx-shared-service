"""Report/dashboard query validation (plan 30, D-A9-13).

`build_query` is the ONE gate every dashboard/report route runs its raw
query-string params through - it resolves the timezone, the UTC window, the
bucket edges (D-A9-8) and validates `userId`/`channelId` tenant/workspace
membership, raising a field-named `ReportValidationError` the router maps to
`422 {fieldErrors}`. `team_column()` is the SOLE seam any report reads the
team dimension through (D-A9-13): it returns `None` until plan 28/A8 adds
`Contact.assigned_team_id`, so a future column turns every report's team
grouping on without touching this module or any report's SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.user import User

from ..models import Channel, Contact
from . import report_windows
from .report_windows import Bucket


class ReportValidationError(Exception):
    """422-worthy - `field` names the offending query param
    (`fieldErrors.<field>`), matching every other omnichannel router's shape."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


def team_column() -> Optional[Any]:
    """D-A9-13: the team dimension column, or `None` until plan 28/A8 adds
    `Contact.assigned_team_id`. Every report reads the dimension through this
    ONE accessor - never a bare `hasattr`/`getattr` scattered per report."""
    return getattr(Contact, "assigned_team_id", None)


def team_available() -> bool:
    return team_column() is not None


@dataclass
class ReportQuery:
    tenant_id: str
    workspace_id: str
    tz_name: str
    tz: ZoneInfo
    granularity: str
    window_start: datetime
    window_end: datetime
    buckets: List[Bucket]
    user_id: Optional[str] = None
    channel_id: Optional[str] = None
    group_by: Optional[str] = None
    # The ORIGINAL `from`/`to` local-date strings the caller sent (S2's
    # `report()` echoes these verbatim in `ReportResponse.range` - the
    # resolved `window_start`/`window_end` above are UTC instants, not the
    # wire's local-date `range` shape).
    from_str: str = ""
    to_str: str = ""


def _require_no_team(team_id: Optional[str], group_by: Optional[str]) -> None:
    """AC-RPT-15: `teamId`/`groupBy=team` are 422 until A8 lands - checked
    BEFORE any other validation so the response always names the actual
    unavailable-dimension request, not an unrelated later failure."""
    if team_available():
        return
    if team_id is not None:
        raise ReportValidationError("teamId", "The team dimension is not available yet.")
    if group_by == "team":
        raise ReportValidationError("groupBy", "The team dimension is not available yet.")


def build_query(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    *,
    from_: str,
    to: str,
    tz: str,
    granularity: Optional[str] = None,
    user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    group_by: Optional[str] = None,
    team_id: Optional[str] = None,
) -> ReportQuery:
    _require_no_team(team_id, group_by)

    try:
        zone = report_windows.resolve_zone(tz)
    except report_windows.InvalidTimezone as exc:
        raise ReportValidationError("tz", f"Unknown timezone: {tz}.") from exc

    try:
        from_date = report_windows.parse_local_date(from_)
    except report_windows.InvalidDateFormat as exc:
        raise ReportValidationError("from", "Must be YYYY-MM-DD.") from exc
    try:
        to_date = report_windows.parse_local_date(to)
    except report_windows.InvalidDateFormat as exc:
        raise ReportValidationError("to", "Must be YYYY-MM-DD.") from exc

    try:
        window_start, window_end = report_windows.resolve_range(from_date, to_date, zone)
    except report_windows.InvalidRangeOrder as exc:
        raise ReportValidationError("to", "Must not be earlier than from.") from exc
    except report_windows.RangeTooWide as exc:
        raise ReportValidationError(
            "to", f"Range cannot exceed {report_windows.MAX_RANGE_DAYS} days."
        ) from exc

    if granularity is None:
        granularity = report_windows.auto_granularity(from_date, to_date)
    elif granularity not in report_windows.GRANULARITIES:
        raise ReportValidationError(
            "granularity", f"Must be one of {', '.join(report_windows.GRANULARITIES)}."
        )

    try:
        buckets = report_windows.bucket_edges(window_start, window_end, zone, granularity)
    except report_windows.BucketLimitExceeded as exc:
        raise ReportValidationError(
            "granularity",
            f"This range would need {exc.count} buckets (max {report_windows.MAX_BUCKETS}); "
            "choose a coarser granularity or a shorter range.",
        ) from exc

    if user_id is not None:
        exists = (
            db.query(User.id).filter(User.id == user_id, User.tenant_id == tenant_id).first()
        )
        if exists is None:
            raise ReportValidationError("userId", "Unknown user.")

    if channel_id is not None:
        exists = (
            db.query(Channel.id)
            .filter(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
            )
            .first()
        )
        if exists is None:
            raise ReportValidationError("channelId", "Unknown channel.")

    return ReportQuery(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        tz_name=tz,
        tz=zone,
        granularity=granularity,
        window_start=window_start,
        window_end=window_end,
        buckets=buckets,
        user_id=user_id,
        channel_id=channel_id,
        group_by=group_by,
        from_str=from_,
        to_str=to,
    )

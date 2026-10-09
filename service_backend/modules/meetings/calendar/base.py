"""``CalendarSource`` - the one adapter seam in S0 (spine §4).

Two more implementations are already planned (``google_oauth`` for tenants that
refuse domain-wide delegation, ``m365_graph`` for Microsoft 365), which is the
only reason this is an interface rather than a direct call.

The source's job is narrow: hand back the events of ONE user's calendar as
``RawEvent``s, plus the token that makes the next read incremental. It decides
nothing about opt-ins, dedupe or persistence - that is the sync service.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from ..models import PLATFORM_MEET, PLATFORM_OTHER, PLATFORM_TEAMS, PLATFORM_ZOOM


class SyncTokenInvalid(Exception):
    """The stored ``syncToken`` was rejected (Google answers HTTP 410).

    The caller drops the token and refetches the whole window - the one recovery
    Google documents for an expired token."""


class CalendarSourceError(Exception):
    """The calendar could not be read at all (bad credentials, no delegation,
    transport). Carries the provider's own message VERBATIM so the operator can
    act on it instead of guessing at "connection failed"."""


@dataclass
class RawEvent:
    """One calendar event as the source saw it - provider-neutral.

    ``cancelled`` is True for an event the calendar has since dropped; the sync
    service removes the mirrored row rather than guessing (AC-S0-10).
    ``conference_url`` is None for an event with no conference link at all, which
    the sync service simply does not mirror.
    """

    external_id: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    title: Optional[str] = None
    organiser_email: Optional[str] = None
    attendees: List[Dict[str, Any]] = field(default_factory=list)
    conference_url: Optional[str] = None
    cancelled: bool = False


@dataclass
class SyncPage:
    """What one read of a calendar returned.

    ``next_sync_token`` is what makes the NEXT read incremental; it is None when
    the source has no token to offer, in which case the next run reads the full
    window again.
    """

    events: List[RawEvent] = field(default_factory=list)
    next_sync_token: Optional[str] = None


class CalendarSource(Protocol):
    """Read one user's calendar."""

    def list_events(
        self,
        *,
        user_email: str,
        sync_token: Optional[str] = None,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> SyncPage:
        """Events for ``user_email``. With ``sync_token`` the read is incremental
        (and raises ``SyncTokenInvalid`` when the token has expired); without one
        it is the full ``time_min``..``time_max`` window."""
        ...


# ── conference-link recognition ──────────────────────────────────────────────
# Shared by every source: which platform a link belongs to is a property of the
# URL, not of the calendar it came from.

_MEET_RE = re.compile(r"https://meet\.google\.com/[a-z0-9\-]+", re.I)
_ZOOM_RE = re.compile(r"https://[a-z0-9.\-]*zoom\.us/[a-z]/[^\s<>\"']+", re.I)
_TEAMS_RE = re.compile(
    r"https://teams\.(?:microsoft|live)\.com/l/meetup-join/[^\s<>\"']+", re.I
)
# Order matters only for reporting; the patterns cannot overlap.
_LINK_PATTERNS = (
    (PLATFORM_MEET, _MEET_RE),
    (PLATFORM_ZOOM, _ZOOM_RE),
    (PLATFORM_TEAMS, _TEAMS_RE),
)


def detect_platform(url: Optional[str]) -> str:
    """Which conference platform a URL belongs to; ``other`` when unrecognised."""
    if not url:
        return PLATFORM_OTHER
    for platform, pattern in _LINK_PATTERNS:
        if pattern.search(url):
            return platform
    return PLATFORM_OTHER


def find_conference_url(*texts: Optional[str]) -> Optional[str]:
    """The first recognised conference link across the given free-text blobs.

    Used for Zoom / Teams meetings, which Google carries in ``location`` or
    ``description`` rather than in ``conferenceData`` (S0 plan §3)."""
    for text in texts:
        if not text:
            continue
        for _platform, pattern in _LINK_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(0)
    return None

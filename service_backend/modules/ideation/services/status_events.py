"""Requester status-update event feed - the S4 hook seam (issue #94, plan
section 7). ``IdeaMergeService`` (S3, ``services/merge.py``) calls these two
functions from INSIDE its own merge/unmerge transaction, at the point the
plan names ("write a merged/unmerged event per member/restored child with a
requester") - so S4 can fill in the real ``idea_status_events`` writer
without restructuring the merge/unmerge service at all.

Both are no-ops today (S3 scope ends at leaving this seam); S4 replaces the
body with the subscriber-driven writer described in plan section 7.1:
recipients = the moved idea plus, on a survivor, each merged child, each
resolved to a Contact with a phone (tenant-scoped), deduped by phone.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.user import User

from ..models import Idea


def record_merge_events(
    db: Session,
    *,
    tenant_id: str,
    survivor: Idea,
    members: List[Idea],
    actor: Optional[User] = None,
) -> None:
    """S4: write one ``kind="merged"`` ``idea_status_events`` row per member
    that resolves to a requester (deduped by phone), in the SAME transaction
    ``IdeaMergeService.merge`` is about to commit. No-op today."""
    return None


def record_unmerge_events(
    db: Session,
    *,
    tenant_id: str,
    restored: List[Idea],
    actor: Optional[User] = None,
) -> None:
    """S4: write one ``kind="unmerged"`` ``idea_status_events`` row per
    restored idea that resolves to a requester, in the SAME transaction
    ``IdeaMergeService.unmerge`` is about to commit. No-op today."""
    return None

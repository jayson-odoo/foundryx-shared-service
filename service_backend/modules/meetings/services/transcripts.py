"""Transcript read service (S3 plan §3.4, AC-S3-8).

The only surface until S5 owns a real transcript UI. Reads scope to the
caller's OWN meetings (a ``meeting_participants`` row carrying their
``user_id``) or ``meetings.manage`` (every meeting in the tenant) - the same
own-vs-manage split ``meetings.view``/``meetings.manage`` already draw
everywhere else (permissions.csv). A meeting that has not reached
``transcribed`` (or ``ready``) yet, or has since FAILED a re-run - which
leaves the OLD ``Transcript`` row behind even though the meeting no longer
carries a current one - reads as not-ready, never a stale row.
"""
from __future__ import annotations

from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import STATUS_READY, STATUS_TRANSCRIBED, Meeting, MeetingParticipant, Transcript, TranscriptSegment


class TranscriptsService:
    def __init__(self, db: Session):
        self.db = db

    def get_for_meeting(
        self,
        tenant_id: str,
        meeting_id: str,
        user_id: str,
        *,
        can_manage: bool = False,
    ) -> Tuple[Meeting, Transcript, List[TranscriptSegment]]:
        meeting = (
            self.db.query(Meeting)
            .filter(Meeting.tenant_id == tenant_id, Meeting.id == meeting_id)
            .first()
        )
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )
        if not can_manage and not self._is_participant(tenant_id, meeting_id, user_id):
            # A meeting that exists but is not the caller's to see is
            # indistinguishable from one that does not exist - same as every
            # other own-scope surface in this module (events.py).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )
        if meeting.status not in (STATUS_TRANSCRIBED, STATUS_READY):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not ready"
            )

        transcript = (
            self.db.query(Transcript)
            .filter(Transcript.tenant_id == tenant_id, Transcript.meeting_id == meeting_id)
            .first()
        )
        if transcript is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not ready"
            )

        segments = (
            self.db.query(TranscriptSegment)
            .filter(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.start_ms.asc(), TranscriptSegment.id.asc())
            .all()
        )
        return meeting, transcript, segments

    def _is_participant(self, tenant_id: str, meeting_id: str, user_id: str) -> bool:
        return (
            self.db.query(MeetingParticipant)
            .filter(
                MeetingParticipant.tenant_id == tenant_id,
                MeetingParticipant.meeting_id == meeting_id,
                MeetingParticipant.user_id == user_id,
            )
            .first()
            is not None
        )

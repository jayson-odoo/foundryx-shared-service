"""Transcript read route (S3 plan §3.4, AC-S3-8).

HTTP + Pydantic only, tenant-scoped. ``meetings.view`` is the base gate;
within it the read further scopes to the caller's OWN meeting (a
``meeting_participants`` row) unless they also hold ``meetings.manage``,
matching ``events.py``'s own-scope convention - a meeting that exists but is
not the caller's, or a foreign tenant's meeting, 404s exactly like one that
has not reached ``transcribed`` yet.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys, require_permission
from app.models.user import User

from ..schemas import TranscriptOut, TranscriptSegmentOut
from ..services.transcripts import TranscriptsService

router = APIRouter()


@router.get("/{meeting_id}/transcript", response_model=TranscriptOut)
def get_transcript(
    meeting_id: str,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> TranscriptOut:
    can_manage = "meetings.manage" in effective_permission_keys(current_user)
    meeting, transcript, segments = TranscriptsService(db).get_for_meeting(
        current_user.tenant_id, meeting_id, current_user.id, can_manage=can_manage
    )
    return TranscriptOut(
        sttProvider=transcript.stt_provider,
        model=transcript.model,
        language=meeting.language,
        segments=[
            TranscriptSegmentOut(
                speaker=seg.speaker,
                startMs=seg.start_ms,
                endMs=seg.end_ms,
                text=seg.text,
                language=seg.language,
            )
            for seg in segments
        ],
    )

"""Minutes read/edit routes (S4 plan §3.2, AC-S4-8/13).

HTTP + Pydantic only. Reads mirror ``transcripts.py``'s own-scope pattern
(``meetings.view`` + participant-or-``meetings.manage``); every mutation
(PUT, regenerate, toggle) needs ``meetings.manage`` - editing or
regenerating someone else's minutes is a tenant-wide capability, not an
own-meeting one.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys, get_actor_user_id, require_permission
from app.models.user import User
from app.schemas.job import JobOut

from ..jobs import enqueue_minutes, minutes_in_flight
from ..models import ActionItem, Minutes
from ..schemas import (
    ActionItemOut,
    MinutesOut,
    MinutesSectionsIn,
    MinutesVersionSummaryOut,
    TopicNoteOut,
)
from ..services.minutes import MinutesService

router = APIRouter()


def _out(
    minutes_row: Minutes, items: list, versions: list
) -> MinutesOut:
    sections = minutes_row.sections_json or {}
    return MinutesOut(
        version=minutes_row.version,
        createdBy=minutes_row.created_by,
        createdAt=minutes_row.created_at,
        promptVersionId=minutes_row.prompt_version_id,
        llmProvider=minutes_row.llm_provider,
        llmModel=minutes_row.llm_model,
        summary=str(sections.get("summary") or ""),
        decisions=list(sections.get("decisions") or []),
        openQuestions=list(sections.get("open_questions") or []),
        topicNotes=[
            TopicNoteOut(topic=str(t.get("topic") or ""), notes=str(t.get("notes") or ""))
            for t in (sections.get("topic_notes") or [])
        ],
        actionItems=[
            ActionItemOut(
                id=item.id,
                text=item.text,
                ownerEmail=item.owner_email,
                dueOn=item.due_on,
                doneAt=item.done_at,
            )
            for item in items
        ],
        versions=[
            MinutesVersionSummaryOut(
                version=v.version, createdBy=v.created_by, createdAt=v.created_at
            )
            for v in versions
        ],
    )


@router.get("/{meeting_id}/minutes", response_model=MinutesOut)
def get_minutes(
    meeting_id: str,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> MinutesOut:
    can_manage = "meetings.manage" in effective_permission_keys(current_user)
    row, items, versions = MinutesService(db).get_latest(
        current_user.tenant_id, meeting_id, current_user.id, can_manage=can_manage
    )
    return _out(row, items, versions)


@router.get("/{meeting_id}/minutes/versions/{version}", response_model=MinutesOut)
def get_minutes_version(
    meeting_id: str,
    version: int,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> MinutesOut:
    can_manage = "meetings.manage" in effective_permission_keys(current_user)
    row, items, versions = MinutesService(db).get_version(
        current_user.tenant_id, meeting_id, version, current_user.id, can_manage=can_manage
    )
    return _out(row, items, versions)


@router.put("/{meeting_id}/minutes", response_model=MinutesOut)
def update_minutes(
    meeting_id: str,
    body: MinutesSectionsIn,
    current_user: User = Depends(require_permission("meetings.manage")),
    db: Session = Depends(get_db),
) -> MinutesOut:
    sections = {
        "summary": body.summary,
        "decisions": list(body.decisions),
        "action_items": [
            {"text": i.text, "owner_email": i.ownerEmail, "due_on": i.dueOn}
            for i in body.actionItems
        ],
        "open_questions": list(body.openQuestions),
        "topic_notes": [{"topic": t.topic, "notes": t.notes} for t in body.topicNotes],
    }
    row, items, versions = MinutesService(db).create_version(
        current_user.tenant_id, meeting_id, sections, current_user.id
    )
    return _out(row, items, versions)


@router.post(
    "/{meeting_id}/minutes/regenerate",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_minutes(
    meeting_id: str,
    current_user: User = Depends(require_permission("meetings.manage")),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> JobOut:
    meeting = MinutesService(db).require_meeting(current_user.tenant_id, meeting_id)
    if minutes_in_flight(db, current_user.tenant_id, meeting_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A minutes job is already running for this meeting."
        )
    job = enqueue_minutes(db, meeting, actor_user_id=actor_id)
    return JobOut.model_validate(job)


@router.post("/action-items/{action_item_id}/toggle", response_model=ActionItemOut)
def toggle_action_item(
    action_item_id: str,
    current_user: User = Depends(require_permission("meetings.manage")),
    db: Session = Depends(get_db),
) -> ActionItemOut:
    row: ActionItem = MinutesService(db).toggle_action_item(
        current_user.tenant_id, action_item_id
    )
    return ActionItemOut(
        id=row.id, text=row.text, ownerEmail=row.owner_email, dueOn=row.due_on, doneAt=row.done_at
    )

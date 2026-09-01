"""Minutes generation pipeline + read/edit service (S4 plan §3.1/3.2).

``generate_minutes`` is the ONE thing the ``meetings.minutes`` job handler
(``jobs.py``) calls: resolve the LLM, render the registry prompt, call it
once (with one corrective retry on a malformed response), and write ONE
versioned ``minutes`` row + its ``action_items``. Every typed failure is a
``MinutesError`` subclass so the job handler can fail the job with a clean
message instead of a crash. A failed run writes NOTHING - the ORM rows are
only ever built AFTER a response parses cleanly, and the one commit at the
end covers all of them together (AC-S4-7).

``MinutesService`` is the read/edit surface the router (``routers/minutes.py``)
drives: latest + a specific version (own-scope, mirroring
``TranscriptsService``), a new human-edited version (append-only), and the
action-item toggle.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.integrations import get_provider
from app.integrations.base import LLMError
from app.models.ai_prompt import AIPromptVersion
from app.models.connection import CONNECTION_STATUS_ERROR, Connection
from app.models.integration_activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, SOURCE_MEETINGS
from app.secrets import decrypt_secret
from app.services.ai_prompt_registry import get_prompt

from ..models import (
    MINUTES_AUTHOR_LLM,
    STATUS_READY,
    ActionItem,
    Meeting,
    MeetingParticipant,
    Minutes,
    Transcript,
    TranscriptSegment,
)
from .settings import MeetingsSettingsService

logger = logging.getLogger("foundryx.meetings")

PROMPT_NAME = "meetings_minutes"
_OPERATION = "minutes_generate"
_REQUIRED_KEYS = ("summary", "decisions", "action_items", "open_questions", "topic_notes")
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class MinutesError(Exception):
    """Base for every typed failure ``generate_minutes`` can raise - the job
    handler catches this and fails the job with the message, never a crash."""


class MinutesResolutionError(MinutesError):
    """No usable LLM connection/credentials could be resolved (AC-S4-5)."""


class MinutesGenerationError(MinutesError):
    """The LLM call, or its structured output, failed after the one
    corrective retry (AC-S4-7)."""


class MinutesShapeError(MinutesError):
    """A parsed response is missing, or mis-types, a required section."""


@dataclass
class ResolvedLLM:
    provider_name: str
    model: str
    credentials: Dict[str, Any]
    config: Dict[str, Any]


# ── LLM resolution (R1, AC-S4-5) ─────────────────────────────────────────────


def resolve_llm(db: Session, tenant_id: str) -> ResolvedLLM:
    """``tenant_settings.llm_connection_id`` if set, else the platform env
    default; raises ``MinutesResolutionError`` when neither is usable.

    A SET connection id that is missing/inactive/undecryptable is a
    misconfiguration, not a "fall through to the platform key" case - the
    tenant made an explicit choice and it must fail loudly rather than
    silently substitute another provider (mirrors ``run_calendar_sync``'s
    Google InvalidToken handling for the same reason).
    """
    from app.config import settings

    tenant_settings = MeetingsSettingsService(db).get(tenant_id)
    connection_id = tenant_settings.llm_connection_id
    if connection_id:
        connection = (
            db.query(Connection)
            .filter(Connection.tenant_id == tenant_id, Connection.id == connection_id)
            .first()
        )
        if connection is None or not connection.is_active:
            raise MinutesResolutionError(
                "The AI connection configured for meeting minutes is missing or "
                "inactive - pick another connection in Meetings Settings."
            )
        try:
            credentials = decrypt_secret(connection.credentials_json)
        except InvalidToken:
            connection.status = CONNECTION_STATUS_ERROR
            connection.last_error = (
                "Stored credentials can no longer be decrypted. Re-enter the "
                "API key and save."
            )
            db.commit()
            raise MinutesResolutionError(connection.last_error) from None
        model = (connection.config_json or {}).get("model") or settings.meetings_llm_model
        return ResolvedLLM(
            provider_name=connection.provider,
            model=str(model),
            credentials=credentials,
            config=dict(connection.config_json or {}),
        )

    if not settings.meetings_llm_api_key:
        raise MinutesResolutionError(
            "No AI connection is configured for meeting minutes - set one in "
            "Meetings Settings, or configure a platform default."
        )
    return ResolvedLLM(
        provider_name=settings.meetings_llm_provider,
        model=settings.meetings_llm_model,
        credentials={"apiKey": settings.meetings_llm_api_key},
        config={},
    )


# ── prompt render ────────────────────────────────────────────────────────────


def _render(template: str, variables: Dict[str, str]) -> str:
    """``{{token}}`` substitution - the registry stores the raw template and
    never renders it itself (``ai_prompt_registry.get_prompt``)."""

    def _sub(match: "re.Match[str]") -> str:
        return str(variables.get(match.group(1), match.group(0)))

    return _TOKEN_RE.sub(_sub, template or "")


def _participants_text(participants: List[MeetingParticipant]) -> str:
    if not participants:
        return "(no participants recorded)"
    return ", ".join(
        f"{p.display_name} <{p.email}>" if p.display_name else p.email for p in participants
    )


def _format_ms(ms: Optional[int]) -> str:
    total_s = max(int(ms or 0), 0) // 1000
    return f"{total_s // 60:02d}:{total_s % 60:02d}"


def _transcript_text(segments: List[TranscriptSegment]) -> str:
    if not segments:
        return "(no transcript segments)"
    lines = []
    for seg in segments:
        speaker = seg.speaker or "Unknown"
        language = seg.language or "unknown"
        end_ms = seg.end_ms if seg.end_ms is not None else seg.start_ms
        lines.append(
            f"[{_format_ms(seg.start_ms)}-{_format_ms(end_ms)}] {speaker} ({language}): {seg.text}"
        )
    return "\n".join(lines)


# ── structured-output discipline (AC-S4-7) ───────────────────────────────────


def _strip_fence(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    body = stripped[first_newline + 1 :] if first_newline != -1 else ""
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def _parse_sections(text: str) -> Dict[str, Any]:
    """Strict-JSON + shape validation. Raises ``MinutesShapeError`` (never a
    bare parse exception) - its message is both what a corrective retry
    prompt is told and what a second failure logs (AC-S4-7)."""
    try:
        data = json.loads(_strip_fence(text))
    except (ValueError, TypeError) as exc:
        raise MinutesShapeError(f"The response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MinutesShapeError("The response was not a JSON object.")
    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise MinutesShapeError(f"Missing section(s): {', '.join(missing)}.")

    if not isinstance(data["summary"], str):
        raise MinutesShapeError("`summary` must be a string.")
    decisions = data["decisions"]
    if not isinstance(decisions, list) or not all(isinstance(d, str) for d in decisions):
        raise MinutesShapeError("`decisions` must be a list of strings.")
    open_questions = data["open_questions"]
    if not isinstance(open_questions, list) or not all(
        isinstance(q, str) for q in open_questions
    ):
        raise MinutesShapeError("`open_questions` must be a list of strings.")

    action_items_raw = data["action_items"]
    if not isinstance(action_items_raw, list):
        raise MinutesShapeError("`action_items` must be a list.")
    action_items = []
    for row in action_items_raw:
        if not isinstance(row, dict) or not str(row.get("text") or "").strip():
            raise MinutesShapeError("Every action item needs a non-empty `text`.")
        owner_email = row.get("owner_email")
        due_on = row.get("due_on")
        action_items.append(
            {
                "text": str(row["text"]),
                "owner_email": owner_email if isinstance(owner_email, str) else None,
                "due_on": due_on if isinstance(due_on, str) else None,
            }
        )

    topic_notes_raw = data["topic_notes"]
    if not isinstance(topic_notes_raw, list):
        raise MinutesShapeError("`topic_notes` must be a list.")
    topic_notes = []
    for row in topic_notes_raw:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("topic"), str)
            or not isinstance(row.get("notes"), str)
        ):
            raise MinutesShapeError("Every topic note needs `topic` and `notes` strings.")
        topic_notes.append({"topic": row["topic"], "notes": row["notes"]})

    return {
        "summary": data["summary"],
        "decisions": list(decisions),
        "action_items": action_items,
        "open_questions": list(open_questions),
        "topic_notes": topic_notes,
    }


def _parse_due_on(value: Optional[str]) -> Optional[date]:
    """An ISO date, or None - never a guess (plan §3.1 step 5)."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# ── activity log (AC-S4-6) ───────────────────────────────────────────────────


def _log_call(
    db: Session,
    *,
    meeting: Meeting,
    provider: str,
    model: str,
    latency_ms: int,
    status: str,
    error: Optional[str] = None,
    response: Optional[Dict[str, Any]] = None,
) -> None:
    """``ActivityLogService.record`` is already failure-isolated (its own
    commit, swallows + logs any exception) - nothing extra needed here for
    "logging failures never fail the job"."""
    from app.activity_log.service import ActivityLogService

    ActivityLogService(db).record(
        tenant_id=meeting.tenant_id,
        source=SOURCE_MEETINGS,
        operation=_OPERATION,
        status=status,
        latency_ms=latency_ms,
        error_message=error,
        external_ref=meeting.id,
        request={"provider": provider, "model": model},
        response=response,
    )


# ── the pipeline ──────────────────────────────────────────────────────────────


def generate_minutes(db: Session, meeting: Meeting) -> Minutes:
    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
    if transcript is None:
        raise MinutesError("This meeting has no transcript to generate minutes from.")
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms.asc(), TranscriptSegment.id.asc())
        .all()
    )
    participants = (
        db.query(MeetingParticipant)
        .filter(MeetingParticipant.meeting_id == meeting.id)
        .order_by(MeetingParticipant.email.asc())
        .all()
    )

    resolved = resolve_llm(db, meeting.tenant_id)
    provider = get_provider(resolved.provider_name)
    if provider is None:
        raise MinutesResolutionError(
            f'Meeting minutes are configured to use an unknown provider '
            f'"{resolved.provider_name}".'
        )

    tenant_settings = MeetingsSettingsService(db).get(meeting.tenant_id)
    prompt = get_prompt(db, PROMPT_NAME)
    base_prompt = _render(
        prompt.text,
        {
            "title": meeting.title or "Untitled meeting",
            "participants": _participants_text(participants),
            "language": tenant_settings.minutes_language or "en",
            "transcript": _transcript_text(segments),
        },
    )

    parsed: Optional[Dict[str, Any]] = None
    validation_error: Optional[str] = None
    for attempt in (1, 2):
        prompt_text = (
            base_prompt
            if attempt == 1
            else (
                base_prompt
                + "\n\nYour previous response was rejected: "
                + str(validation_error)
                + "\n\nReturn ONLY the corrected JSON, no prose, no markdown fence."
            )
        )
        started = time.monotonic()
        try:
            result = provider.complete(
                resolved.config,
                resolved.credentials,
                model=resolved.model,
                system="",
                messages=[{"role": "user", "content": prompt_text}],
                temperature=0,
            )
        except LLMError as exc:
            # A transport/credential failure is not "structured output was
            # wrong" - it gets no corrective retry, just a clean fail.
            latency_ms = int((time.monotonic() - started) * 1000)
            _log_call(
                db,
                meeting=meeting,
                provider=resolved.provider_name,
                model=resolved.model,
                latency_ms=latency_ms,
                status=ACTIVITY_ERROR,
                error=str(exc),
            )
            raise MinutesGenerationError(str(exc)) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            parsed = _parse_sections(result.text or "")
        except MinutesShapeError as exc:
            validation_error = str(exc)
            _log_call(
                db,
                meeting=meeting,
                provider=resolved.provider_name,
                model=resolved.model,
                latency_ms=latency_ms,
                status=ACTIVITY_ERROR,
                error=validation_error,
                response={"raw": (result.text or "")[:2000]},
            )
            if attempt == 2:
                raise MinutesGenerationError(
                    "The model's structured response was invalid after a "
                    f"corrective retry: {validation_error}"
                ) from exc
            continue

        _log_call(
            db,
            meeting=meeting,
            provider=resolved.provider_name,
            model=resolved.model,
            latency_ms=latency_ms,
            status=ACTIVITY_SUCCESS,
            response={"sections": list(parsed.keys())},
        )
        break

    assert parsed is not None  # every path above raises or sets it

    version_row = (
        db.query(AIPromptVersion)
        .filter(AIPromptVersion.name == PROMPT_NAME, AIPromptVersion.version == prompt.version)
        .first()
        if prompt.version is not None
        else None
    )

    next_version = (
        db.query(func.coalesce(func.max(Minutes.version), 0))
        .filter(Minutes.meeting_id == meeting.id)
        .scalar()
        or 0
    ) + 1
    minutes_row = Minutes(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        version=next_version,
        sections_json=parsed,
        created_by=MINUTES_AUTHOR_LLM,
        prompt_version_id=version_row.id if version_row else None,
        llm_provider=resolved.provider_name,
        llm_model=resolved.model,
    )
    db.add(minutes_row)
    db.flush()
    for item in parsed["action_items"]:
        db.add(
            ActionItem(
                tenant_id=meeting.tenant_id,
                minutes_id=minutes_row.id,
                text=item["text"],
                owner_email=item["owner_email"],
                due_on=_parse_due_on(item["due_on"]),
            )
        )
    meeting.status = STATUS_READY
    db.commit()
    db.refresh(minutes_row)
    return minutes_row


# ── read/edit service (S4 plan §3.2) ─────────────────────────────────────────


class MinutesService:
    """Backs ``routers/minutes.py``. Reads mirror ``TranscriptsService``'s
    own-scope check (participant or ``meetings.manage``); writes assume the
    caller already holds ``meetings.manage`` (the router's dependency)."""

    def __init__(self, db: Session):
        self.db = db

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

    def _scoped_meeting(
        self, tenant_id: str, meeting_id: str, user_id: str, *, can_manage: bool
    ) -> Meeting:
        meeting = (
            self.db.query(Meeting)
            .filter(Meeting.tenant_id == tenant_id, Meeting.id == meeting_id)
            .first()
        )
        if meeting is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found")
        if not can_manage and not self._is_participant(tenant_id, meeting_id, user_id):
            # Same own-scope convention as transcripts.py: not-yours reads
            # exactly like not-found.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found")
        return meeting

    def _versions(self, meeting_id: str) -> List[Minutes]:
        return (
            self.db.query(Minutes)
            .filter(Minutes.meeting_id == meeting_id)
            .order_by(Minutes.version.desc())
            .all()
        )

    def _action_items(self, minutes_id: str) -> List[ActionItem]:
        return (
            self.db.query(ActionItem)
            .filter(ActionItem.minutes_id == minutes_id)
            .order_by(ActionItem.created_at.asc(), ActionItem.id.asc())
            .all()
        )

    def get_latest(
        self, tenant_id: str, meeting_id: str, user_id: str, *, can_manage: bool
    ) -> Tuple[Minutes, List[ActionItem], List[Minutes]]:
        self._scoped_meeting(tenant_id, meeting_id, user_id, can_manage=can_manage)
        versions = self._versions(meeting_id)
        if not versions:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Minutes not ready")
        latest = versions[0]
        return latest, self._action_items(latest.id), versions

    def get_version(
        self,
        tenant_id: str,
        meeting_id: str,
        version: int,
        user_id: str,
        *,
        can_manage: bool,
    ) -> Tuple[Minutes, List[ActionItem], List[Minutes]]:
        self._scoped_meeting(tenant_id, meeting_id, user_id, can_manage=can_manage)
        row = (
            self.db.query(Minutes)
            .filter(Minutes.meeting_id == meeting_id, Minutes.version == version)
            .first()
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Minutes version not found")
        return row, self._action_items(row.id), self._versions(meeting_id)

    def create_version(
        self, tenant_id: str, meeting_id: str, sections: Dict[str, Any], user_id: str
    ) -> Tuple[Minutes, List[ActionItem], List[Minutes]]:
        """A human edit - the NEXT version, original(s) untouched (AC-S4-8)."""
        meeting = (
            self.db.query(Meeting)
            .filter(Meeting.tenant_id == tenant_id, Meeting.id == meeting_id)
            .first()
        )
        if meeting is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found")
        next_version = (
            self.db.query(func.coalesce(func.max(Minutes.version), 0))
            .filter(Minutes.meeting_id == meeting_id)
            .scalar()
            or 0
        ) + 1
        row = Minutes(
            tenant_id=tenant_id,
            meeting_id=meeting_id,
            version=next_version,
            sections_json=sections,
            created_by=user_id,
        )
        self.db.add(row)
        self.db.flush()
        for item in sections.get("action_items", []):
            self.db.add(
                ActionItem(
                    tenant_id=tenant_id,
                    minutes_id=row.id,
                    text=item["text"],
                    owner_email=item.get("owner_email"),
                    due_on=_parse_due_on(item.get("due_on")),
                )
            )
        self.db.commit()
        self.db.refresh(row)
        return row, self._action_items(row.id), self._versions(meeting_id)

    def toggle_action_item(self, tenant_id: str, action_item_id: str) -> ActionItem:
        row = (
            self.db.query(ActionItem)
            .filter(ActionItem.tenant_id == tenant_id, ActionItem.id == action_item_id)
            .first()
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Action item not found")
        row.done_at = None if row.done_at is not None else datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return row

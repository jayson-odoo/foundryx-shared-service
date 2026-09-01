"""AI prompt registry - runtime resolver + admin CRUD (Meetings S4, R4/R5).

Immutable-versions + movable-labels model, ported from sorento's
`ai_prompt_registry.py` / `ai_prompt_service.py`, merged into ONE module here:
shared-service has a single consumer (`meetings_minutes`) so far, not
sorento's ~20-key registry - a second consumer is the trigger to split the
runtime resolver back out from the admin CRUD surface.

Runtime resolution:
- `get_prompt(db, name, label="production")` - in-process TTL cache keyed by
  `(name, label)`; on cache miss SELECT the labelled version; on a DB error
  OR a missing row, fall back to the hardcoded spec for `name` with
  `version=None`. NEVER raises on a DB-unreachable condition - the minutes
  job must survive an empty registry (AC-S4-9).

Admin surface (routes in `app/api/v1/ai_prompts.py`):
- `list_prompts` / `get_prompt_detail` / `save_version` (append-only,
  next version per name) / `set_label` (repoints + busts the cache). NO
  update/delete route for a version exists anywhere - versions are immutable.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_prompt import AIPromptLabel, AIPromptVersion
from app.models.user import User

logger = logging.getLogger(__name__)

# "production" is what a running job resolves; "staging" rides along on the
# wire shape (it costs nothing) with no publish button yet in the v1 editor
# UI - trigger to add one: a second consumer that wants a stage-before-
# publish step (plan §3.3).
LABELS = ("production", "staging")

# In-process cache TTL (seconds). `set_label` also busts the cache immediately
# for zero-lag rollout; the TTL bounds staleness for any out-of-process writer.
CACHE_TTL_SECONDS = 60.0

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class PromptNotFound(Exception):
    """`name` is not a registered prompt key."""


class PromptVersionNotFound(Exception):
    """`version_id` does not belong to this prompt name."""


class InvalidLabel(Exception):
    """`label` is not one of `LABELS`."""


class PromptValidationError(Exception):
    """A `save_version` call failed template/commit-message validation."""

    def __init__(self, message: str, *, unknown_tokens: list[str], missing_vars: list[str]):
        super().__init__(message)
        self.message = message
        self.unknown_tokens = unknown_tokens
        self.missing_vars = missing_vars


# --------------------------------------------------------------------------- #
# Hardcoded fallback (the seed migration copies this verbatim as version 1 -  #
# keep the two in sync).                                                       #
# --------------------------------------------------------------------------- #


def _meetings_minutes_fallback() -> str:
    """System prompt for `meetings.minutes` (plan §3.1). Renders the
    transcript + participants into a structured-JSON minutes request; the
    five keys are the M14 section contract (AC-S4-2)."""
    return (
        'You are taking minutes for a meeting titled "{{title}}".\n\n'
        "Participants: {{participants}}\n\n"
        "Write the minutes in {{language}}. Use only what is said in the "
        "transcript below - never invent a decision, an action item, or a "
        "fact that was not said.\n\n"
        "Transcript:\n"
        "{{transcript}}\n\n"
        "Return STRICT JSON only, no prose, no markdown fence, with exactly "
        "these keys:\n\n"
        "{\n"
        '  "summary": "one short paragraph capturing what the meeting covered",\n'
        '  "decisions": ["decision made, one per entry"],\n'
        '  "action_items": [\n'
        '    {"text": "what needs to be done", "owner_email": "email as stated or null", '
        '"due_on": "YYYY-MM-DD or null"}\n'
        "  ],\n"
        '  "open_questions": ["question raised but not resolved"],\n'
        '  "topic_notes": [\n'
        '    {"topic": "topic discussed", "notes": "key points raised on that topic"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Every list may be empty ([]) when the transcript has nothing for it - "
        "never invent content to fill a section.\n"
        "- owner_email is the participant's email exactly as it appears in the "
        "transcript or participant list; use null when no owner is named.\n"
        "- due_on is an ISO date (YYYY-MM-DD); use null when no date is stated.\n"
        "- Write summary, decisions, open_questions and topic_notes in "
        "{{language}}. Never translate or alter the transcript itself.\n"
    )


@dataclass(frozen=True)
class _PromptSpec:
    variables: list[str]
    fallback: Callable[[], str]


_REGISTRY: dict[str, _PromptSpec] = {
    "meetings_minutes": _PromptSpec(
        variables=["title", "participants", "language", "transcript"],
        fallback=_meetings_minutes_fallback,
    ),
}


def prompt_names() -> list[str]:
    """Ordered list of registered prompt names."""
    return list(_REGISTRY.keys())


# --------------------------------------------------------------------------- #
# Template variable helpers                                                    #
# --------------------------------------------------------------------------- #


def extract_tokens(template: str) -> set[str]:
    """All `{{token}}` names found in a template body."""
    return set(_TOKEN_RE.findall(template or ""))


def validate_template(name: str, template: str) -> tuple[list[str], list[str]]:
    """Return `(unknown_tokens, missing_vars)` for a template against a key's
    declared variables. `unknown` = tokens present but not declared (would
    leak literally -> blocks save); `missing` = declared vars absent (soft
    warn, save still succeeds)."""
    spec = _REGISTRY.get(name)
    declared = set(spec.variables) if spec else set()
    found = extract_tokens(template)
    unknown = sorted(found - declared)
    missing = sorted(declared - found)
    return unknown, missing


# --------------------------------------------------------------------------- #
# Runtime resolver + cache                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class RenderedPrompt:
    text: str
    name: str
    version: Optional[int]


@dataclass
class _CacheEntry:
    text: str
    version: int
    expires_at: float


_CACHE: dict[tuple[str, str], _CacheEntry] = {}


def bust_cache(name: Optional[str] = None) -> None:
    """Immediate cache invalidation. Called by `set_label` so the very next
    `get_prompt` reflects the newly-published version (AC-S4-9)."""
    if name is None:
        _CACHE.clear()
        return
    for key in [k for k in _CACHE if k[0] == name]:
        _CACHE.pop(key, None)


def _fallback(name: str) -> RenderedPrompt:
    spec = _REGISTRY.get(name)
    text = spec.fallback() if spec else ""
    return RenderedPrompt(text=text, name=name, version=None)


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # pragma: no cover - defensive
        pass


def get_prompt(db: Session, name: str, label: str = "production") -> RenderedPrompt:
    """Resolve a prompt to its live text + version. TTL cache by
    `(name, label)` -> labelled version -> hardcoded fallback. Never raises
    on a DB error; returns the fallback with `version=None` (AC-S4-9)."""
    now = time.monotonic()
    cached = _CACHE.get((name, label))
    if cached is not None and cached.expires_at > now:
        return RenderedPrompt(text=cached.text, name=name, version=cached.version)

    try:
        row = (
            db.query(AIPromptVersion)
            .join(AIPromptLabel, AIPromptLabel.version_id == AIPromptVersion.id)
            .filter(AIPromptLabel.name == name, AIPromptLabel.label == label)
            .first()
        )
    except Exception:
        logger.warning(
            "prompt resolve failed name=%s label=%s; using fallback", name, label, exc_info=True
        )
        _safe_rollback(db)
        return _fallback(name)

    if row is None:
        return _fallback(name)

    _CACHE[(name, label)] = _CacheEntry(
        text=row.template, version=row.version, expires_at=now + CACHE_TTL_SECONDS
    )
    return RenderedPrompt(text=row.template, name=name, version=row.version)


# --------------------------------------------------------------------------- #
# Admin CRUD (routes in app/api/v1/ai_prompts.py)                              #
# --------------------------------------------------------------------------- #


def _labels_map(db: Session, name: str) -> dict[str, Optional[int]]:
    """`{production: int|None, staging: int|None}` for a prompt name."""
    rows = (
        db.query(AIPromptLabel.label, AIPromptVersion.version)
        .join(AIPromptVersion, AIPromptVersion.id == AIPromptLabel.version_id)
        .filter(AIPromptLabel.name == name)
        .all()
    )
    by_label = {r.label: int(r.version) for r in rows}
    return {lbl: by_label.get(lbl) for lbl in LABELS}


def _labels_for_version(db: Session, name: str) -> dict[str, list[str]]:
    """Map `version_id` -> list of labels pointing at it, for a prompt name."""
    rows = (
        db.query(AIPromptLabel.label, AIPromptLabel.version_id)
        .filter(AIPromptLabel.name == name)
        .all()
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(str(r.version_id), []).append(r.label)
    return out


def _user_names(db: Session, user_ids: list[Optional[str]]) -> dict[str, str]:
    ids = list({i for i in user_ids if i})
    if not ids:
        return {}
    rows = db.query(User.id, User.name).filter(User.id.in_(ids)).all()
    return {str(r.id): r.name for r in rows}


def list_prompts(db: Session) -> list[dict]:
    """One summary row per registered prompt name (list page, plan §3.4)."""
    summaries = []
    for name in prompt_names():
        labels = _labels_map(db, name)
        latest = (
            db.query(AIPromptVersion)
            .filter(AIPromptVersion.name == name)
            .order_by(AIPromptVersion.version.desc())
            .first()
        )
        actor_id = latest.created_by if latest is not None else None
        names = _user_names(db, [actor_id])
        summaries.append(
            {
                "name": name,
                "production_version": labels.get("production"),
                "latest_version": int(latest.version) if latest is not None else None,
                "updated_at": latest.created_at if latest is not None else None,
                "updated_by_name": names.get(str(actor_id)) if actor_id else None,
            }
        )
    return summaries


def get_prompt_detail(db: Session, name: str) -> dict:
    """Full version history + label pointers for one prompt name."""
    spec = _REGISTRY.get(name)
    if spec is None:
        raise PromptNotFound(name)
    rows = (
        db.query(AIPromptVersion)
        .filter(AIPromptVersion.name == name)
        .order_by(AIPromptVersion.version.desc())
        .all()
    )
    label_map = _labels_for_version(db, name)
    names = _user_names(db, [r.created_by for r in rows])
    versions = [
        {
            "id": str(r.id),
            "version": int(r.version),
            "template": r.template,
            "commit_message": r.commit_message,
            "created_by_name": names.get(str(r.created_by)) if r.created_by else None,
            "created_at": r.created_at,
            "labels": label_map.get(str(r.id), []),
        }
        for r in rows
    ]
    return {
        "name": name,
        "variables": list(spec.variables),
        "labels": _labels_map(db, name),
        "versions": versions,
    }


def save_version(
    db: Session, name: str, *, template: str, commit_message: str, user_id: Optional[str]
) -> dict:
    """Append a new immutable version (`max(version)+1` per name). Unknown
    `{{token}}` hard-blocks; a blank commit message hard-blocks. Never
    updates or deletes an existing row (AC-S4-9)."""
    spec = _REGISTRY.get(name)
    if spec is None:
        raise PromptNotFound(name)
    if not (commit_message or "").strip():
        raise PromptValidationError(
            "Commit message is required.", unknown_tokens=[], missing_vars=[]
        )
    unknown, missing = validate_template(name, template)
    if unknown:
        raise PromptValidationError(
            "Template contains unknown variable token(s) that are not declared "
            "for this prompt and would render literally: " + ", ".join(unknown),
            unknown_tokens=unknown,
            missing_vars=missing,
        )
    next_version = (
        int(
            db.query(func.coalesce(func.max(AIPromptVersion.version), 0))
            .filter(AIPromptVersion.name == name)
            .scalar()
            or 0
        )
        + 1
    )
    row = AIPromptVersion(
        name=name,
        version=next_version,
        template=template,
        variables=list(spec.variables),
        commit_message=commit_message.strip(),
        created_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    names = _user_names(db, [user_id])
    return {
        "id": str(row.id),
        "version": int(row.version),
        "template": row.template,
        "commit_message": row.commit_message,
        "created_by_name": names.get(str(user_id)) if user_id else None,
        "created_at": row.created_at,
        "labels": [],  # a new version lands unlabelled
    }


def set_label(
    db: Session, name: str, *, label: str, version_id: str, user_id: Optional[str]
) -> dict:
    """Move a label to a version (publish/rollback) - one UPSERT + an
    immediate cache bust so the next job resolution sees it (AC-S4-9)."""
    if _REGISTRY.get(name) is None:
        raise PromptNotFound(name)
    if label not in LABELS:
        raise InvalidLabel(label)
    version = (
        db.query(AIPromptVersion)
        .filter(AIPromptVersion.id == version_id, AIPromptVersion.name == name)
        .first()
    )
    if version is None:
        raise PromptVersionNotFound(version_id)
    label_row = (
        db.query(AIPromptLabel)
        .filter(AIPromptLabel.name == name, AIPromptLabel.label == label)
        .first()
    )
    if label_row is None:
        label_row = AIPromptLabel(name=name, label=label, version_id=version_id, updated_by=user_id)
        db.add(label_row)
    else:
        label_row.version_id = version_id
        label_row.updated_by = user_id
    db.commit()
    bust_cache(name)
    return get_prompt_detail(db, name)

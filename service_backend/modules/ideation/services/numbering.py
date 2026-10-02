"""Idea numbering (S1, AC-1111/1112) - a Postgres sequence with a SQLite
(tests) fallback. Mirrors ``app/repositories/numbering_repository.py``'s
SAVEPOINT retry pattern (``get_or_create_counter_for_update``): the caller
mints a candidate, flushes inside a nested transaction, and retries on a
unique-violation rather than pre-checking (race-safe on Postgres; a no-op
retry loop on the single-connection SQLite test engine).
"""
import re
import secrets

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Idea

_NUMBER_RE = re.compile(r"^IDEA-(\d+)$")


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _next_number_pg(db: Session) -> int:
    from ..db import IDEATION_SCHEMA

    return db.execute(
        text(f'SELECT nextval(\'"{IDEATION_SCHEMA}".ideas_idea_number_seq\')')
    ).scalar()


def _next_number_fallback(db: Session) -> int:
    """Non-Postgres (SQLite tests): max existing numeric suffix + 1. Not
    concurrency-safe by itself - the caller (``mint_idea_identity``) retries
    under a SAVEPOINT on a unique-violation."""
    best = 0
    for (value,) in db.query(Idea.idea_number).filter(Idea.idea_number.isnot(None)):
        m = _NUMBER_RE.match(value or "")
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def next_idea_number(db: Session) -> str:
    """Format ``IDEA-<n, zero-padded to at least 4 digits>`` - grows past
    9999 without wrapping or truncating (``IDEA-10000``)."""
    n = _next_number_pg(db) if _is_postgres(db) else _next_number_fallback(db)
    return f"IDEA-{n:04d}"


def mint_idea_identity(db: Session, idea: Idea) -> None:
    """Idempotently mint ``idea.idea_number`` + ``idea.status_token`` together
    (both unique, both minted exactly once). A no-op when both are already
    set (idempotent re-fire of the completion sink, AC-A-16/20)."""
    need_number = not idea.idea_number
    need_token = not idea.status_token
    if not need_number and not need_token:
        return
    for _ in range(5):
        if need_number:
            idea.idea_number = next_idea_number(db)
        if need_token:
            idea.status_token = secrets.token_urlsafe(24)
        try:
            with db.begin_nested():
                db.flush()
            return
        except IntegrityError:
            if need_number:
                idea.idea_number = None
            if need_token:
                idea.status_token = None
            continue
    raise RuntimeError(  # pragma: no cover - defensive; a real collision storm
        "Could not mint a unique idea_number/status_token after 5 attempts."
    )

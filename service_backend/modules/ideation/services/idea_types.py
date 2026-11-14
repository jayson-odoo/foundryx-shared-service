"""Idea type catalog (SS-IDEA-TYPE) - the ONE place that knows which idea types
exist and how a caller-supplied ``type`` resolves.

Allowed values live in the ``app_ideation.idea_types`` table (never a hardcoded
list in a router): ``idea`` (default) and ``issue`` today; adding a type = a new
row in ``DEFAULT_IDEA_TYPES`` (+ a backfill migration for live DBs), no new path.
Every create surface (WhatsApp intake, embed, operator) and the list filter call
:func:`resolve_idea_type` / :func:`resolve_idea_type_filter` so validation is
identical everywhere."""
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.api_errors import ApiError

from ..models import IdeaType

# (key, label, sort_order, is_default). Insert-if-missing seed + migration 0019.
DEFAULT_IDEA_TYPES = (
    ("idea", "Idea", 0, True),
    ("issue", "Issue", 1, False),
)
FALLBACK_DEFAULT_TYPE = "idea"


def seed_idea_types(db: Session) -> None:
    """Insert-if-missing the catalog rows (idempotent; an existing row's label is
    left as-is so a later relabel survives a reseed)."""
    existing = {r.key for r in db.query(IdeaType.key).all()}
    for key, label, order, is_default in DEFAULT_IDEA_TYPES:
        if key not in existing:
            db.add(IdeaType(key=key, label=label, sort_order=order, is_default=is_default))
    db.commit()


def list_idea_types(db: Session) -> List[IdeaType]:
    return db.query(IdeaType).order_by(IdeaType.sort_order.asc(), IdeaType.key.asc()).all()


def default_idea_type(db: Session) -> str:
    row = db.query(IdeaType).filter(IdeaType.is_default.is_(True)).first()
    return row.key if row is not None else FALLBACK_DEFAULT_TYPE


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _unknown(value: str, db: Session) -> ApiError:
    allowed = ", ".join(t.key for t in list_idea_types(db))
    return ApiError(
        422,
        "unknown_type",
        f"type '{value}' is not a known idea type (allowed: {allowed}).",
    )


def resolve_idea_type(db: Session, value: Optional[str]) -> str:
    """Caller ``type`` → a catalog key. Missing/blank = the default type (``idea``);
    case-insensitive; an unknown value is a typed 422 ``unknown_type`` (never a
    silent fallback - a typo must not file an issue as an idea)."""
    key = _normalize(value)
    if not key:
        return default_idea_type(db)
    if db.query(IdeaType.key).filter(IdeaType.key == key).first() is None:
        raise _unknown(value or "", db)
    return key


def idea_type_label(db: Session, key: Optional[str]) -> str:
    row = db.query(IdeaType).filter(IdeaType.key == (key or "")).first()
    return row.label if row is not None else (key or FALLBACK_DEFAULT_TYPE).capitalize()


def resolve_idea_type_filter(
    db: Session, values: Optional[Iterable[str]]
) -> Optional[List[str]]:
    """List-filter values → catalog keys (multi-select: repeated params and/or
    comma-separated). ``None``/empty = no type filter. Unknown = 422."""
    keys: List[str] = []
    for raw in values or []:
        for part in (raw or "").split(","):
            k = _normalize(part)
            if k and k not in keys:
                keys.append(k)
    if not keys:
        return None
    known = {r.key for r in db.query(IdeaType.key).filter(IdeaType.key.in_(keys)).all()}
    for k in keys:
        if k not in known:
            raise _unknown(k, db)
    return keys


def upgrade_idea_type_sql(schema: str) -> List[str]:
    """Idempotent Postgres DDL+seed for the idea-type rollout. ONE source used by
    migration 0019 AND ``install()`` (so a legacy create_all DB that only gets the
    stamp path still gains the column), and handed to crew as ``crew-migration``.
    Order matters: catalog → seed rows → column (existing rows = 'idea') → FK
    (needs the 'idea' row) → index."""
    s = schema
    values = ", ".join(
        f"('{k}', '{label}', {order}, {'true' if d else 'false'})"
        for k, label, order, d in DEFAULT_IDEA_TYPES
    )
    return [
        f'CREATE TABLE IF NOT EXISTS "{s}".idea_types ('
        "  key VARCHAR PRIMARY KEY,"
        "  label VARCHAR NOT NULL,"
        "  sort_order INTEGER NOT NULL DEFAULT 0,"
        "  is_default BOOLEAN NOT NULL DEFAULT false"
        ")",
        f'INSERT INTO "{s}".idea_types (key, label, sort_order, is_default) '
        f"VALUES {values} ON CONFLICT (key) DO NOTHING",
        f'ALTER TABLE "{s}".ideas ADD COLUMN IF NOT EXISTS type VARCHAR NOT NULL DEFAULT \'idea\'',
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_namespace n "
        f"ON n.oid = c.connamespace WHERE c.conname = 'fk_ideas_type_idea_types' AND n.nspname = '{s}') "
        f'THEN ALTER TABLE "{s}".ideas ADD CONSTRAINT fk_ideas_type_idea_types '
        f'FOREIGN KEY (type) REFERENCES "{s}".idea_types (key); '
        "END IF; END $$",
        f'CREATE INDEX IF NOT EXISTS ix_ideas_type ON "{s}".ideas (type)',
    ]

"""Deterministic text-similarity dedup (Slice 6, AC-A-21/30/31/32).

**No LLM, no embedding model (D20).** Duplicate detection is a single deterministic
query over existing OLTP Idea rows (the source of truth) - no derived vector
artifact is stored. It runs **inline** in the ``create_idea`` path, scoped to
``(tenant, product)`` so a similar problem under a different product is never a
false positive.

Dialect-aware similarity:

- **Postgres** - the ``pg_trgm`` extension's ``similarity(a, b)`` over the same
  ``(tenant, product)``, accelerated by a GIN trigram index (provisioned by the
  migration via :func:`ensure_pg_trgm_index`). Matches at/above
  :data:`PG_SIMILARITY_THRESHOLD`.
- **SQLite (tests) / any non-Postgres** - a pure-Python ``difflib`` ratio fallback
  over normalized text, so the dedup UNIT TESTS run GREEN with no live Postgres.
  Matches at/above :data:`FALLBACK_SIMILARITY_THRESHOLD`.

The two thresholds differ on purpose: ``pg_trgm`` (trigram overlap) and ``difflib``
(longest-matching-subsequence ratio) are different metrics on different scales for
the same pair of strings; each threshold is tuned to its own metric.

Only **real, captured-or-beyond** ideas are dedup candidates: an unconfirmed
draft is not yet a real capture (D-CONFIRM), so half-finished drafts never
shadow each other; and a draft that itself resolved to ``rejected``
(cancelled) or ``duplicate`` (voted onto another idea, S1) is a dead-end
shell, not a real idea, so it is excluded too - otherwise a voted draft could
itself get offered as a "duplicate" to the NEXT similar submitter instead of
the real original it pointed at.
"""
import difflib
import re
from typing import Iterable, List, Optional, Tuple, Union

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..db import IDEATION_SCHEMA
from ..models import Idea
from .statuses import idea_status_id, initial_idea_status_id

# pg_trgm trigram-overlap score in [0, 1]; 0.3 is the pg_trgm default and a
# sensible floor for "clearly the same idea, differently worded".
PG_SIMILARITY_THRESHOLD = 0.3
# difflib SequenceMatcher ratio in [0, 1]; near-duplicate rephrasings score ~0.65+
# while unrelated sentences score well under 0.5.
FALLBACK_SIMILARITY_THRESHOLD = 0.55

_WS = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


ExcludeIds = Union[str, Iterable[str], None]


def _normalize_exclude_ids(exclude_id: ExcludeIds) -> List[str]:
    """Accept a single id (the existing call shape) OR an iterable of ids (S1
    - a draft excludes both itself and every ``declined_candidates`` id)."""
    if exclude_id is None:
        return []
    if isinstance(exclude_id, str):
        return [exclude_id]
    return [x for x in exclude_id if x]


class DedupService:
    """Inline, deterministic per-(tenant, product) dedup (AC-A-32)."""

    def __init__(self, db: Session):
        self.db = db

    def find_duplicate(
        self,
        tenant_id: str,
        product_id: str,
        problem_text: str,
        exclude_id: ExcludeIds = None,
        is_test: bool = False,
    ) -> Optional[str]:
        """Return the id of an existing (non-draft) Idea in the same
        ``(tenant, product)`` whose problem text is a high similarity match to
        ``problem_text``, or ``None``. Deterministic; picks the single best match.

        ``exclude_id`` accepts either a single id (the draft's own) or an
        iterable of ids (S1, AC-1110) - a draft with ``declined_candidates``
        excludes every one of them too, so a candidate the submitter chose
        "keep separate" on is never re-offered.

        ``is_test`` scopes candidates to the SAME test/real lane (issue #1179):
        a test idea only ever matches other test ideas, and a real idea only
        ever matches other real ideas - a console/``--say`` walk can never
        upvote a real idea, and a real submitter can never get folded into a
        test one.
        """
        needle = _normalize(problem_text)
        if not needle:
            return None

        excludes = _normalize_exclude_ids(exclude_id)
        if self._is_postgres():
            return self._find_duplicate_pg(tenant_id, product_id, needle, excludes, is_test)
        return self._find_duplicate_fallback(tenant_id, product_id, needle, excludes, is_test)

    # ── dialect detection ─────────────────────────────────────────────────────
    def _is_postgres(self) -> bool:
        bind = self.db.get_bind()
        return bool(bind is not None and bind.dialect.name == "postgresql")

    # ── Postgres path - pg_trgm similarity() over the same (tenant, product) ────
    def _find_duplicate_pg(
        self,
        tenant_id: str,
        product_id: str,
        needle: str,
        excludes: List[str],
        is_test: bool = False,
    ) -> Optional[str]:
        dead_ids = [
            s for s in (
                initial_idea_status_id(self.db, tenant_id),
                idea_status_id(self.db, "rejected", tenant_id),
                idea_status_id(self.db, "duplicate", tenant_id),
            )
            if s is not None
        ]
        exclude_clause = "AND id NOT IN :excludes " if excludes else ""
        dead_clause = "AND status_id NOT IN :dead_statuses " if dead_ids else ""
        sql = text(
            f'SELECT id, similarity(lower(problem), :needle) AS sim '
            f'FROM "{IDEATION_SCHEMA}".ideas '
            "WHERE tenant_id = :tenant AND product_id = :product "
            "AND is_test = :is_test "
            f"{exclude_clause}"
            f"{dead_clause}"
            "AND similarity(lower(problem), :needle) >= :threshold "
            "ORDER BY sim DESC, id ASC LIMIT 1"
        )
        params = {
            "needle": needle,
            "tenant": tenant_id,
            "product": product_id,
            "is_test": is_test,
            "threshold": PG_SIMILARITY_THRESHOLD,
        }
        if excludes:
            sql = sql.bindparams(bindparam("excludes", expanding=True))
            params["excludes"] = excludes
        if dead_ids:
            sql = sql.bindparams(bindparam("dead_statuses", expanding=True))
            params["dead_statuses"] = dead_ids
        row = self.db.execute(sql, params).first()
        return row[0] if row is not None else None

    # ── Fallback path - difflib ratio in Python (SQLite tests) ─────────────────
    def _find_duplicate_fallback(
        self,
        tenant_id: str,
        product_id: str,
        needle: str,
        excludes: List[str],
        is_test: bool = False,
    ) -> Optional[str]:
        dead_ids = [
            s for s in (
                initial_idea_status_id(self.db, tenant_id),
                idea_status_id(self.db, "rejected", tenant_id),
                idea_status_id(self.db, "duplicate", tenant_id),
            )
            if s is not None
        ]
        q = (
            self.db.query(Idea.id, Idea.problem)
            .filter(
                Idea.tenant_id == tenant_id,
                Idea.product_id == product_id,
                Idea.is_test.is_(is_test),
            )
        )
        if excludes:
            q = q.filter(~Idea.id.in_(excludes))
        if dead_ids:
            q = q.filter(~Idea.status_id.in_(dead_ids))

        best: Tuple[float, Optional[str]] = (0.0, None)
        matcher = difflib.SequenceMatcher()
        matcher.set_seq2(needle)
        for cand_id, problem in q.all():
            matcher.set_seq1(_normalize(problem or ""))
            score = matcher.ratio()
            if score >= FALLBACK_SIMILARITY_THRESHOLD and (
                score > best[0] or (score == best[0] and (best[1] is None or cand_id < best[1]))
            ):
                best = (score, cand_id)
        return best[1]


def ensure_pg_trgm_index(bind: Connection) -> None:
    """Provision ``pg_trgm`` + a GIN trigram index on the Idea dedup text
    (AC-A-30). **Postgres-only** - a graceful no-op on SQLite / any non-Postgres
    engine (the test engine has no ``pg_trgm``). There is **no ``vector`` extension
    and no ``embedding`` column** (D20)."""
    if bind is None or bind.dialect.name != "postgresql":
        return
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ideas_problem_trgm "
            f'ON "{IDEATION_SCHEMA}".ideas USING gin (lower(problem) gin_trgm_ops)'
        )
    )

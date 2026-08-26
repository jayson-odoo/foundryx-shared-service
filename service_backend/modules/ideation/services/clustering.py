"""Idea clustering (Phase B-i slice 4, AC-BI-30/31, Bi-D14).

**Retrieval, then grouping** - the same cheap-candidates-into-an-expensive-model
trick the plan calls out (D10-A/Bi-D14):

1. ``pg_trgm`` narrows to CANDIDATE neighbours within one ``(tenant, product)`` -
   an all-pairs self-join reusing the Phase A dedup index/threshold (NOT
   ``find_duplicate``, which returns a single best match). A SQLite ``difflib``
   fallback keeps the routine suite offline.
2. ONE ``AiClient.complete`` call (the lower-level seam, NOT the grill) groups +
   **names** the candidates via a forced ``{clusters:[{label, ideaIds[]}]}``
   schema - so semantically-related ideas with no lexical overlap can still land
   in the same cluster (the reason pure trigram was insufficient).

**Degrades, never blocks (AC-BI-30).** No pgvector, no embeddings. If the LLM
call fails (or no agent/connection resolves), the trigram candidate GROUPS are
returned UNGROUPED (the connected components of the similarity graph) - a 502
must never reach the board. The model only ever SUGGESTS; nothing auto-promotes
(AC-BI-31/D16 - promotion is a separate explicit human action).

Anti-SSTI: idea text is passed to the model as DATA (message content), never
interpolated into a prompt template that is evaluated.
"""
from __future__ import annotations

import difflib
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.client import AiClient, any_llm_connection
from app.repositories.ai_repository import AgentRepository

from ..db import IDEATION_SCHEMA
from ..models import Idea
from ..schemas import ClusterSuggestionOut, ClusterSuggestionsOut
from .dedup import (
    FALLBACK_SIMILARITY_THRESHOLD,
    PG_SIMILARITY_THRESHOLD,
    _normalize,
)
from .ideas import IdeaReadService
from .statuses import initial_idea_status_id

# The auto-seeded per-tenant grill agent - reused for the cheap grouping call
# (Bi-D20b). Bound by its STABLE key so a rename never breaks resolution.
CLUSTER_AGENT_KEY = "ideation-grill"

# Cap the candidate set fed to one LLM call so a large board never bloats a
# prompt (the trace payload cap + cost guard, mirrors the plan's size caps).
_MAX_CANDIDATES = 60
# Bound the in-Python difflib fallback's O(n²) pairwise scan (AC-BI-30 "never
# blocks") - only reached when the pg_trgm path errors (missing extension, etc.)
# or on a non-Postgres engine. A few hundred newest ideas is plenty of signal.
_FALLBACK_MAX_ROWS = 400


class ClusteringService:
    """Suggest idea clusters for a ``(tenant, product)`` - retrieval + grouping,
    graceful degradation (AC-BI-30/31)."""

    def __init__(self, db: Session):
        self.db = db
        self._reader = IdeaReadService(db)

    # ── public ───────────────────────────────────────────────────────────────
    def suggest(
        self,
        tenant_id: str,
        *,
        product_id: Optional[str] = None,
        voter_id: Optional[str] = None,
    ) -> ClusterSuggestionsOut:
        """Cluster suggestions across one product (``product_id`` given) or every
        product with candidate neighbours in the tenant (``None``). Always
        tenant-scoped first."""
        product_ids = (
            [product_id]
            if product_id
            else self._products_with_ideas(tenant_id)
        )
        clusters: List[ClusterSuggestionOut] = []
        degraded = False
        for pid in product_ids:
            product_clusters, product_degraded = self._suggest_for_product(
                tenant_id, pid, voter_id
            )
            clusters.extend(product_clusters)
            degraded = degraded or product_degraded
        return ClusterSuggestionsOut(clusters=clusters, degraded=degraded)

    # ── per-product ──────────────────────────────────────────────────────────
    def _suggest_for_product(
        self, tenant_id: str, product_id: str, voter_id: Optional[str]
    ) -> Tuple[List[ClusterSuggestionOut], bool]:
        pairs = self._candidate_pairs(tenant_id, product_id)
        if not pairs:
            return [], False
        components = _components(pairs)
        candidate_ids = sorted({i for pair in pairs for i in pair})[:_MAX_CANDIDATES]
        texts = self._idea_texts(tenant_id, candidate_ids)

        grouped, degraded = self._group(
            tenant_id, candidate_ids, texts, components
        )
        return self._serialize(tenant_id, product_id, grouped, voter_id), degraded

    # ── retrieval (trigram candidates) ─────────────────────────────────────────
    def _is_postgres(self) -> bool:
        bind = self.db.get_bind()
        return bool(bind is not None and bind.dialect.name == "postgresql")

    def _candidate_pairs(
        self, tenant_id: str, product_id: str
    ) -> List[Tuple[str, str]]:
        """High-similarity id pairs of NON-draft ideas in the same
        ``(tenant, product)`` (``a.id < b.id`` - each unordered pair once).

        Clustering must DEGRADE, never block the board (AC-BI-30): if the
        ``pg_trgm`` retrieval fails (extension not installed, etc.), fall back to
        the in-Python ``difflib`` pass rather than 500 the endpoint."""
        if self._is_postgres():
            try:
                return self._candidate_pairs_pg(tenant_id, product_id)
            except SQLAlchemyError:
                # The failed statement poisons the transaction - roll back before
                # the fallback runs another query on the same session.
                self.db.rollback()
                return self._candidate_pairs_fallback(tenant_id, product_id)
        return self._candidate_pairs_fallback(tenant_id, product_id)

    def _candidate_pairs_pg(
        self, tenant_id: str, product_id: str
    ) -> List[Tuple[str, str]]:
        draft_id = initial_idea_status_id(self.db, tenant_id)
        sql = text(
            "SELECT a.id AS a_id, b.id AS b_id "
            f'FROM "{IDEATION_SCHEMA}".ideas a '
            f'JOIN "{IDEATION_SCHEMA}".ideas b ON a.id < b.id '
            "WHERE a.tenant_id = :tenant AND b.tenant_id = :tenant "
            "AND a.product_id = :product AND b.product_id = :product "
            "AND (:draft IS NULL OR a.status_id <> :draft) "
            "AND (:draft IS NULL OR b.status_id <> :draft) "
            "AND similarity(lower(a.problem), lower(b.problem)) >= :threshold "
            "ORDER BY a.id ASC, b.id ASC"
        )
        rows = self.db.execute(
            sql,
            {
                "tenant": tenant_id,
                "product": product_id,
                "draft": draft_id,
                "threshold": PG_SIMILARITY_THRESHOLD,
            },
        ).all()
        return [(r.a_id, r.b_id) for r in rows]

    def _candidate_pairs_fallback(
        self, tenant_id: str, product_id: str
    ) -> List[Tuple[str, str]]:
        draft_id = initial_idea_status_id(self.db, tenant_id)
        q = self.db.query(Idea.id, Idea.problem).filter(
            Idea.tenant_id == tenant_id, Idea.product_id == product_id
        )
        if draft_id is not None:
            q = q.filter(Idea.status_id != draft_id)
        # Bound the O(n²) difflib pass - clustering must DEGRADE, never block, even
        # on a large board when the pg_trgm path errored (AC-BI-30). Cap the row
        # set so the pairwise scan stays bounded; the newest ideas are the most
        # relevant clustering candidates.
        q = q.order_by(Idea.created_at.desc(), Idea.id.desc()).limit(
            _FALLBACK_MAX_ROWS
        )
        rows = [(rid, _normalize(problem or "")) for rid, problem in q.all()]
        pairs: List[Tuple[str, str]] = []
        matcher = difflib.SequenceMatcher()
        for i in range(len(rows)):
            matcher.set_seq2(rows[i][1])
            for j in range(i + 1, len(rows)):
                matcher.set_seq1(rows[j][1])
                if matcher.ratio() >= FALLBACK_SIMILARITY_THRESHOLD:
                    a, b = rows[i][0], rows[j][0]
                    pairs.append((a, b) if a < b else (b, a))
        return pairs

    # ── grouping (LLM, degrade to components) ──────────────────────────────────
    def _group(
        self,
        tenant_id: str,
        candidate_ids: List[str],
        texts: Dict[str, str],
        components: List[List[str]],
    ) -> Tuple[List[Tuple[str, List[str]]], bool]:
        """Return ``([(label, ideaIds)], degraded)``. Tries ONE grouping call;
        on any failure falls back to the trigram components ungrouped."""
        agent = AgentRepository(self.db).get_by_key(tenant_id, CLUSTER_AGENT_KEY)
        if agent is None or not agent.is_enabled:
            return _fallback_clusters(components), True
        # The auto-seeded agent may be connectionless until a key is added; heal
        # it lazily (mirrors the grill's ``_resolve_agent``) so grouping lights up
        # the moment a tenant/platform LLM connection exists.
        if not agent.connection_id:
            conn = any_llm_connection(self.db, tenant_id)
            if conn is not None:
                agent.connection_id = conn.id
                self.db.flush()

        system = (
            "You group near-duplicate or closely related PRODUCT IDEAS into "
            "clusters and give each cluster a short, specific label (max 6 words). "
            "Only group ideas that describe the same underlying problem or request. "
            "Return every input idea id in at most one cluster; ideas that do not "
            "belong with any other may be omitted. Never invent ids."
        )
        listing = "\n".join(f"- {iid}: {texts.get(iid, '')}" for iid in candidate_ids)
        messages = [
            {
                "role": "user",
                "content": (
                    "Group these ideas into clusters:\n\n" + listing
                ),
            }
        ]
        schema = {
            "type": "object",
            "properties": {
                "clusters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "ideaIds": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["label", "ideaIds"],
                    },
                }
            },
            "required": ["clusters"],
        }

        try:
            result, _trace = AiClient(self.db).complete(
                tenant_id=tenant_id,
                agent=agent,
                system=system,
                messages=messages,
                output_schema=schema,
            )
            # The completion flushed its trace; commit so it survives even though
            # this is a read endpoint (the caller does not commit).
            self.db.commit()
        except Exception:
            # DEGRADE on ANY grouping failure (AC-BI-30) - the provider contract
            # says failures are LLMError, but a transport/JSON error the adapter
            # missed must NEVER 500 the board. Roll back any poisoned txn state,
            # then persist the flushed ERROR trace best-effort, then fall back to
            # the ungrouped connected components.
            try:
                self.db.commit()
            except SQLAlchemyError:
                self.db.rollback()
            return _fallback_clusters(components), True

        grouped = _parse_clusters(result.structured, set(candidate_ids))
        if not grouped:
            # The model returned nothing usable (e.g. the offline stub, which
            # never fills a non-string array) - fall back to the components so a
            # zero-config workspace still sees suggestions.
            return _fallback_clusters(components), True
        return grouped, False

    # ── helpers ────────────────────────────────────────────────────────────────
    def _products_with_ideas(self, tenant_id: str) -> List[str]:
        rows = (
            self.db.query(Idea.product_id)
            .filter(Idea.tenant_id == tenant_id, Idea.product_id.isnot(None))
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    def _idea_texts(self, tenant_id: str, ids: List[str]) -> Dict[str, str]:
        if not ids:
            return {}
        rows = (
            self.db.query(Idea.id, Idea.problem)
            .filter(Idea.id.in_(ids), Idea.tenant_id == tenant_id)
            .all()
        )
        return {rid: (problem or "").strip() for rid, problem in rows}

    def _serialize(
        self,
        tenant_id: str,
        product_id: str,
        grouped: List[Tuple[str, List[str]]],
        voter_id: Optional[str],
    ) -> List[ClusterSuggestionOut]:
        wanted = sorted({i for _label, ids in grouped for i in ids})
        ideas = (
            {
                i.id: i
                for i in self.db.query(Idea)
                .filter(Idea.id.in_(wanted), Idea.tenant_id == tenant_id)
                .all()
            }
            if wanted
            else {}
        )
        serialized = {
            i.id: out
            for i, out in zip(
                ideas.values(),
                self._reader.serialize_many(list(ideas.values()), voter_id),
            )
        }
        out: List[ClusterSuggestionOut] = []
        for label, ids in grouped:
            members = [serialized[i] for i in ids if i in serialized]
            # A suggested cluster is a GROUP - a single idea is not a cluster
            # (the human can still promote one idea alone from the list).
            if len(members) < 2:
                continue
            out.append(
                ClusterSuggestionOut(
                    label=label,
                    productId=product_id,
                    ideaIds=[m.id for m in members],
                    ideas=members,
                )
            )
        return out


# ── module-level pure helpers ─────────────────────────────────────────────────


def _components(pairs: List[Tuple[str, str]]) -> List[List[str]]:
    """Connected components (union-find) of the similarity graph - the trigram
    candidate GROUPS used as the ungrouped degrade fallback."""
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)
    groups: Dict[str, List[str]] = {}
    for node in parent:
        groups.setdefault(find(node), []).append(node)
    return [sorted(members) for members in groups.values() if len(members) >= 2]


def _fallback_clusters(components: List[List[str]]) -> List[Tuple[str, List[str]]]:
    return [("Similar ideas", members) for members in components]


def _parse_clusters(
    structured, valid_ids: set
) -> List[Tuple[str, List[str]]]:
    """Parse the model's ``{clusters:[{label, ideaIds}]}`` - dropping unknown ids
    (never resolve a hallucinated id) and de-duping within a cluster. An id may
    appear in at most one cluster (first wins)."""
    if not isinstance(structured, dict):
        return []
    raw = structured.get("clusters")
    if not isinstance(raw, list):
        return []
    used: set = set()
    out: List[Tuple[str, List[str]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        ids = item.get("ideaIds")
        if not isinstance(label, str) or not isinstance(ids, list):
            continue
        kept: List[str] = []
        for iid in ids:
            if isinstance(iid, str) and iid in valid_ids and iid not in used:
                used.add(iid)
                kept.append(iid)
        if kept:
            out.append((label.strip() or "Similar ideas", kept))
    return out

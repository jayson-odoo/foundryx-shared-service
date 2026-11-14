"""Similar ideas for one idea (plan 20 S3, AC-20-20/21, D2).

**Meaning, not word overlap.** ONE ``AiClient.complete`` call (the tenant's
``ideation-grill`` agent - the same seam as :mod:`clustering`) ranks the live
candidate ideas on the same product by how much they describe the same need.
There is deliberately NO ``pg_trgm`` / word-match fallback (owner rule): if the
model fails or returns nothing usable the result is ``available: False`` and
the UI offers Retry.

Candidates = same tenant + product + test/real lane, live survivors (the
dedup candidacy predicate), never the idea itself or its merged children,
capped at the newest :data:`MAX_CANDIDATES`. The model only ever ranks ids it
was given - any other id is dropped. Idea text is message DATA, never a prompt
template (anti-SSTI).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.client import AiClient, any_llm_connection
from app.models.user import User
from app.repositories.ai_repository import AgentRepository

from ..models import Idea
from ..schemas import SimilarIdeasOut
from .clustering import CLUSTER_AGENT_KEY
from .dedup import dead_candidate_status_ids
from .ideas import IdeaReadService

# Prompt size / cost guard: ~60 short idea texts is ~4k input tokens.
MAX_CANDIDATES = 60
# Characters of each idea's text sent to the model.
_TEXT_CAP = 400

_SYSTEM = (
    "You compare PRODUCT IDEAS. Given one TARGET idea and a list of CANDIDATE "
    "ideas, return the ids of the candidates that describe the same or a closely "
    "related underlying need as the target, most similar first. Leave out "
    "candidates that are about something different. Return an empty list when "
    "none are similar. Only use ids from the candidate list; never invent ids."
)

_SCHEMA = {
    "type": "object",
    "properties": {"ideaIds": {"type": "array", "items": {"type": "string"}}},
    "required": ["ideaIds"],
}


def _idea_text(idea: Idea) -> str:
    parts = [idea.title or "", idea.problem or "", idea.desired_outcome or ""]
    text = " | ".join(p.strip() for p in parts if p and p.strip())
    return " ".join(text.split())[:_TEXT_CAP]


class SimilarIdeasService:
    def __init__(self, db: Session, content_prefix: Optional[str] = None):
        self.db = db
        self._reader = (
            IdeaReadService(db, content_prefix) if content_prefix else IdeaReadService(db)
        )

    def similar(
        self,
        tenant_id: str,
        idea_id: str,
        *,
        voter_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> SimilarIdeasOut:
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        candidates = self._candidates(tenant_id, idea)
        if not candidates:
            return SimilarIdeasOut(available=True, ideas=[])
        ranked_ids = self._rank(tenant_id, idea, candidates)
        if ranked_ids is None:
            return SimilarIdeasOut(available=False, ideas=[])
        by_id = {c.id: c for c in candidates}
        ordered = [by_id[i] for i in ranked_ids]
        return SimilarIdeasOut(
            available=True,
            ideas=self._reader.serialize_many(
                ordered, voter_id, tenant_id=tenant_id, actor=actor
            ),
        )

    def _candidates(self, tenant_id: str, idea: Idea) -> List[Idea]:
        dead_ids = dead_candidate_status_ids(self.db, tenant_id)
        q = self.db.query(Idea).filter(
            Idea.tenant_id == tenant_id,
            Idea.product_id == idea.product_id,
            Idea.is_test.is_(bool(idea.is_test)),
            Idea.merged_into_id.is_(None),
            Idea.id != idea.id,
        )
        if dead_ids:
            q = q.filter(~Idea.status_id.in_(dead_ids))
        return q.order_by(Idea.created_at.desc(), Idea.id.asc()).limit(MAX_CANDIDATES).all()

    def _rank(self, tenant_id: str, idea: Idea, candidates: List[Idea]) -> Optional[List[str]]:
        """Ranked candidate ids, or ``None`` when the AI is unavailable or its
        output is unusable (never a word-match fallback)."""
        agent = AgentRepository(self.db).get_by_key(tenant_id, CLUSTER_AGENT_KEY)
        if agent is None or not agent.is_enabled:
            return None
        if not agent.connection_id:
            # Use a configured connection for THIS call only - a read (any
            # viewer, or the CRM iframe opening a tab) must never rewrite the
            # tenant's agent config, so detach the row before pointing it.
            conn = any_llm_connection(self.db, tenant_id)
            if conn is not None:
                self.db.expunge(agent)
                agent.connection_id = conn.id
        listing = "\n".join(f"- {c.id}: {_idea_text(c)}" for c in candidates)
        messages = [
            {
                "role": "user",
                "content": f"TARGET: {_idea_text(idea)}\n\nCANDIDATES:\n{listing}",
            }
        ]
        try:
            result, _trace = AiClient(self.db).complete(
                tenant_id=tenant_id,
                agent=agent,
                system=_SYSTEM,
                messages=messages,
                output_schema=_SCHEMA,
            )
            self.db.commit()  # keep the trace (read endpoint, caller won't commit)
        except Exception:
            try:
                self.db.commit()
            except SQLAlchemyError:
                self.db.rollback()
            return None
        structured = result.structured
        raw = structured.get("ideaIds") if isinstance(structured, dict) else None
        if not isinstance(raw, list):
            return None
        valid = {c.id for c in candidates}
        out: List[str] = []
        for iid in raw:
            if isinstance(iid, str) and iid in valid and iid not in out:
                out.append(iid)
        return out

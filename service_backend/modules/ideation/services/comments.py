"""Idea comments (plan 19, AC-19-02..10, 28..32).

Flat storage with ONE reply level: ``parent_id`` always points at a top-level
comment of the same idea (a reply-to-reply is normalised to its top-level
parent). Delete is soft; a deleted top-level comment that still has live replies
is returned as a placeholder (no body, no author), a deleted comment without live
replies is omitted. ``author_id`` never leaves this service.

Every query is scoped by ``tenant_id`` AND ``idea_id`` (the polymorphic-id rule):
a comment / parent id from another idea or tenant resolves to nothing (404).
Operator, embed and public callers share these methods; they differ only in the
``CommentViewer`` they pass and the author they stamp.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Idea, IdeaComment
from ..schemas import IdeaCommentOut

AUTHOR_USER = "user"
AUTHOR_EMBED = "embed"
AUTHOR_PUBLIC = "public"


@dataclass(frozen=True)
class CommentViewer:
    """Who is looking. ``kind``/``id`` identify the author principal for the
    ``isMine`` / ``canEdit`` flags (``None`` = an anonymous public reader);
    ``can_moderate`` = may delete anyone's comment (``ideation.triage.manage``)."""

    kind: Optional[str] = None
    id: Optional[str] = None
    can_moderate: bool = False


PUBLIC_VIEWER = CommentViewer()


def public_author_id(idea_id: str) -> str:
    return f"public:{idea_id}"


class IdeaCommentService:
    def __init__(self, db: Session):
        self.db = db

    # ---- scoping -----------------------------------------------------------

    def _idea_or_404(self, tenant_id: str, idea_id: str) -> Idea:
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        return idea

    def _comment_or_404(self, tenant_id: str, idea_id: str, comment_id: str) -> IdeaComment:
        row = (
            self.db.query(IdeaComment)
            .filter(
                IdeaComment.id == comment_id,
                IdeaComment.idea_id == idea_id,
                IdeaComment.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(404, "Comment not found.")
        return row

    def _refuse_if_merged_child(self, idea: Idea) -> None:
        # Same refusal as voting on a merged child (AC-19-08).
        from .actions import IdeaActionService

        IdeaActionService(self.db)._refuse_if_merged_child(idea)

    @staticmethod
    def _is_mine(row: IdeaComment, viewer: CommentViewer) -> bool:
        return (
            viewer.kind is not None
            and viewer.id is not None
            and row.author_kind == viewer.kind
            and row.author_id == viewer.id
        )

    def _out(self, row: IdeaComment, viewer: CommentViewer, *, placeholder: bool = False) -> IdeaCommentOut:
        if placeholder or row.deleted_at is not None:
            return IdeaCommentOut(
                id=row.id,
                ideaId=row.idea_id,
                parentId=row.parent_id,
                authorName=None,
                authorKind=row.author_kind,
                body=None,
                isDeleted=True,
                isMine=False,
                canEdit=False,
                canDelete=False,
                createdAt=row.created_at,
                editedAt=row.edited_at,
            )
        mine = self._is_mine(row, viewer)
        return IdeaCommentOut(
            id=row.id,
            ideaId=row.idea_id,
            parentId=row.parent_id,
            authorName=row.author_name,
            authorKind=row.author_kind,
            body=row.body,
            isDeleted=False,
            isMine=mine,
            canEdit=mine,
            canDelete=mine or viewer.can_moderate,
            createdAt=row.created_at,
            editedAt=row.edited_at,
        )

    # ---- reads -------------------------------------------------------------

    def list(self, tenant_id: str, idea_id: str, viewer: CommentViewer) -> List[IdeaCommentOut]:
        self._idea_or_404(tenant_id, idea_id)
        return self._list_for(tenant_id, idea_id, viewer)

    def list_public(self, idea: Idea) -> List[IdeaCommentOut]:
        """The thread of THIS idea (a resolved public-token idea) for an anonymous
        reader - never a survivor's thread, flags always false."""
        return self._list_for(idea.tenant_id, idea.id, PUBLIC_VIEWER)

    def _list_for(self, tenant_id: str, idea_id: str, viewer: CommentViewer) -> List[IdeaCommentOut]:
        rows = (
            self.db.query(IdeaComment)
            .filter(IdeaComment.idea_id == idea_id, IdeaComment.tenant_id == tenant_id)
            .order_by(IdeaComment.created_at.asc(), IdeaComment.id.asc())
            .all()
        )
        parents_with_live_replies: Set[str] = {
            r.parent_id for r in rows if r.deleted_at is None and r.parent_id
        }
        out: List[IdeaCommentOut] = []
        for r in rows:
            if r.deleted_at is None:
                out.append(self._out(r, viewer))
            elif r.parent_id is None and r.id in parents_with_live_replies:
                out.append(self._out(r, viewer, placeholder=True))
        return out

    # ---- writes ------------------------------------------------------------

    def _normalised_parent_id(
        self, tenant_id: str, idea_id: str, parent_id: Optional[str]
    ) -> Optional[str]:
        if not parent_id:
            return None
        parent = (
            self.db.query(IdeaComment)
            .filter(
                IdeaComment.id == parent_id,
                IdeaComment.idea_id == idea_id,
                IdeaComment.tenant_id == tenant_id,
                IdeaComment.deleted_at.is_(None),
            )
            .first()
        )
        if parent is None:
            raise HTTPException(404, "Comment not found.")
        return parent.parent_id or parent.id

    def _insert(
        self,
        idea: Idea,
        *,
        body: str,
        parent_id: Optional[str],
        author_kind: str,
        author_id: str,
        author_name: Optional[str],
        viewer: CommentViewer,
    ) -> IdeaCommentOut:
        self._refuse_if_merged_child(idea)
        row = IdeaComment(
            tenant_id=idea.tenant_id,
            idea_id=idea.id,
            parent_id=self._normalised_parent_id(idea.tenant_id, idea.id, parent_id),
            author_kind=author_kind,
            author_id=author_id,
            author_name=author_name,
            body=body,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._out(row, viewer)

    def create(
        self,
        tenant_id: str,
        idea_id: str,
        *,
        body: str,
        parent_id: Optional[str],
        author_kind: str,
        author_id: str,
        author_name: Optional[str],
        viewer: CommentViewer,
    ) -> IdeaCommentOut:
        idea = self._idea_or_404(tenant_id, idea_id)
        return self._insert(
            idea,
            body=body,
            parent_id=parent_id,
            author_kind=author_kind,
            author_id=author_id,
            author_name=author_name,
            viewer=viewer,
        )

    def create_public(
        self, idea: Idea, *, body: str, parent_id: Optional[str], author_name: str
    ) -> IdeaCommentOut:
        return self._insert(
            idea,
            body=body,
            parent_id=parent_id,
            author_kind=AUTHOR_PUBLIC,
            author_id=public_author_id(idea.id),
            author_name=author_name,
            viewer=PUBLIC_VIEWER,
        )

    def edit(
        self, tenant_id: str, idea_id: str, comment_id: str, *, body: str, viewer: CommentViewer
    ) -> IdeaCommentOut:
        idea = self._idea_or_404(tenant_id, idea_id)
        row = self._comment_or_404(tenant_id, idea_id, comment_id)
        if row.deleted_at is not None:
            raise HTTPException(404, "Comment not found.")
        if not self._is_mine(row, viewer):
            raise HTTPException(403, "Only the author can edit a comment.")
        self._refuse_if_merged_child(idea)
        row.body = body
        row.edited_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return self._out(row, viewer)

    def delete(
        self, tenant_id: str, idea_id: str, comment_id: str, *, viewer: CommentViewer,
        can_comment: bool,
    ) -> None:
        """Soft delete. Allowed for the author (who also holds the comment
        permission) or a moderator; else 403."""
        self._idea_or_404(tenant_id, idea_id)
        row = self._comment_or_404(tenant_id, idea_id, comment_id)
        if row.deleted_at is not None:
            raise HTTPException(404, "Comment not found.")
        if not (viewer.can_moderate or (can_comment and self._is_mine(row, viewer))):
            raise HTTPException(403, "You cannot delete this comment.")
        row.deleted_at = datetime.now(timezone.utc)
        self.db.commit()

    def purge_for_idea(self, tenant_id: str, idea_id: str) -> None:
        """Hard-remove every comment of an idea (idea delete, AC-19-09). Replies
        first - the self-FK would otherwise refuse the parent. No commit."""
        q = self.db.query(IdeaComment).filter(
            IdeaComment.idea_id == idea_id, IdeaComment.tenant_id == tenant_id
        )
        q.filter(IdeaComment.parent_id.isnot(None)).delete(synchronize_session=False)
        q.delete(synchronize_session=False)

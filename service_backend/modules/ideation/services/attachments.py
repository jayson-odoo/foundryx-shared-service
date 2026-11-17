"""Idea attachment uploads (plan sprint-5/15 B1, AC-15-14..19).

An operator or embed user uploads a file onto an idea: sniffed by magic bytes
(the declared type is ignored), stored in the tenant's storage under
``ideation/ideas/<idea_id>/<attachment_id>``, recorded on ``idea_attachments``.
Every lookup is tenant-scoped (idea AND attachment resolved WITH ``tenant_id``).
"""
import re
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.storage import storage_for_tenant
from app.uploads import detect_attachment_mime

from ..models import Idea, IdeaAttachment, IdeaComment
from ..schemas import IdeaAttachmentOut


# Refuse an upload once an idea already carries this many attachments (report
# AND comment files together) / a comment this many.
MAX_ATTACHMENTS_PER_IDEA = 50
MAX_ATTACHMENTS_PER_COMMENT = 10
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean_filename(filename: str, fallback: str) -> str:
    name = _CONTROL_CHARS.sub("", filename or "").strip()[:255].strip()
    return name or fallback


def _kind_for(mime: str) -> str:
    prefix = mime.split("/", 1)[0]
    return prefix if prefix in ("image", "video", "audio") else "file"


class IdeaAttachmentService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_idea(self, tenant_id: str, idea_id: str) -> None:
        """404 unless the idea is in the tenant (cheap check before reading a body)."""
        idea = (
            self.db.query(Idea.id)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Feedback not found.")

    def upload(
        self,
        tenant_id: str,
        idea_id: str,
        filename: str,
        content: bytes,
        *,
        content_prefix: str = "/ideation/ideas",
        comment_id: Optional[str] = None,
    ) -> IdeaAttachmentOut:
        """Store one upload. ``comment_id`` attaches it to that comment (which
        must be live and belong to THIS idea and tenant, else 404); without it the
        file is report-level. Who may attach is the caller's check
        (``comment_for_upload`` first, then the author test)."""
        self.ensure_idea(tenant_id, idea_id)
        if comment_id is not None:
            self.comment_for_upload(tenant_id, idea_id, comment_id)
        mime = detect_attachment_mime(content, filename)
        if mime is None:
            raise HTTPException(415, "This file type is not supported.")
        existing = (
            self.db.query(func.count(IdeaAttachment.id))
            .filter(IdeaAttachment.idea_id == idea_id, IdeaAttachment.tenant_id == tenant_id)
            .scalar()
        )
        if (existing or 0) >= MAX_ATTACHMENTS_PER_IDEA:
            raise HTTPException(422, "This feedback has reached its attachment limit.")
        if comment_id is not None:
            on_comment = (
                self.db.query(func.count(IdeaAttachment.id))
                .filter(
                    IdeaAttachment.comment_id == comment_id,
                    IdeaAttachment.tenant_id == tenant_id,
                )
                .scalar()
            )
            if (on_comment or 0) >= MAX_ATTACHMENTS_PER_COMMENT:
                raise HTTPException(422, "This comment has reached its attachment limit.")
        attachment_id = str(uuid.uuid4())
        storage_key = storage_for_tenant(self.db, tenant_id).save(
            f"ideation/ideas/{idea_id}/{attachment_id}", content, mime
        )
        kind = _kind_for(mime)
        name = _clean_filename(filename, kind)
        row = IdeaAttachment(
            id=attachment_id,
            tenant_id=tenant_id,
            idea_id=idea_id,
            source_msg_id=f"upload:{attachment_id}",
            kind=kind,
            url="",
            filename=name,
            storage_key=storage_key,
            mime=mime,
            size_bytes=len(content),
            comment_id=comment_id,
        )
        self.db.add(row)
        self.db.commit()
        return IdeaAttachmentOut(
            id=row.id,
            kind=row.kind,
            name=name,
            url="",
            sizeBytes=row.size_bytes,
            contentPath=f"{content_prefix}/{idea_id}/attachments/{row.id}/content",
        )

    def comment_for_upload(self, tenant_id: str, idea_id: str, comment_id: str) -> IdeaComment:
        """The live comment an upload targets; 404 when it is unknown, deleted, or
        outside this idea / tenant (a stored id is never resolved bare)."""
        row = (
            self.db.query(IdeaComment)
            .filter(
                IdeaComment.id == comment_id,
                IdeaComment.idea_id == idea_id,
                IdeaComment.tenant_id == tenant_id,
                IdeaComment.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            raise HTTPException(404, "Comment not found.")
        return row

    @staticmethod
    def to_out(row: IdeaAttachment, content_prefix: str) -> IdeaAttachmentOut:
        return IdeaAttachmentOut(
            id=row.id,
            kind=row.kind,
            name=(row.filename or "").strip() or row.kind,
            url=row.url or "",
            sizeBytes=row.size_bytes,
            contentPath=(
                f"{content_prefix}/{row.idea_id}/attachments/{row.id}/content"
                if row.storage_key
                else None
            ),
        )

    def by_comment(
        self, tenant_id: str, comment_ids: Iterable[str], content_prefix: str = "/ideation/ideas"
    ) -> Dict[str, List[IdeaAttachmentOut]]:
        """``{comment_id: [files]}`` in ONE query (no N+1), oldest first."""
        ids = list(comment_ids)
        if not ids:
            return {}
        rows = (
            self.db.query(IdeaAttachment)
            .filter(IdeaAttachment.comment_id.in_(ids), IdeaAttachment.tenant_id == tenant_id)
            .order_by(IdeaAttachment.created_at.asc(), IdeaAttachment.id.asc())
            .all()
        )
        out: Dict[str, List[IdeaAttachmentOut]] = {}
        for r in rows:
            out.setdefault(r.comment_id, []).append(self.to_out(r, content_prefix))
        return out

    def report_level(
        self, tenant_id: str, idea_id: str, content_prefix: str = "/ideation/ideas"
    ) -> List[IdeaAttachmentOut]:
        rows = (
            self.db.query(IdeaAttachment)
            .filter(
                IdeaAttachment.idea_id == idea_id,
                IdeaAttachment.tenant_id == tenant_id,
                IdeaAttachment.comment_id.is_(None),
            )
            .order_by(IdeaAttachment.created_at.asc(), IdeaAttachment.id.asc())
            .all()
        )
        return [self.to_out(r, content_prefix) for r in rows]

    def comment_id_of(self, tenant_id: str, idea_id: str, attachment_id: str) -> Optional[str]:
        """The ``comment_id`` of an attachment (None = report-level, or unknown)."""
        return (
            self.db.query(IdeaAttachment.comment_id)
            .filter(
                IdeaAttachment.id == attachment_id,
                IdeaAttachment.idea_id == idea_id,
                IdeaAttachment.tenant_id == tenant_id,
            )
            .scalar()
        )

    def content(
        self, tenant_id: str, idea_id: str, attachment_id: str
    ) -> Tuple[str, str, str]:
        """``(storage_key, mime, filename)`` of an uploaded attachment; 404 when it
        is outside the tenant/idea or is a URL-backed capture (no stored bytes)."""
        row = (
            self.db.query(IdeaAttachment)
            .filter(
                IdeaAttachment.id == attachment_id,
                IdeaAttachment.idea_id == idea_id,
                IdeaAttachment.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None or not row.storage_key:
            raise HTTPException(404, "Attachment not found.")
        return row.storage_key, row.mime or "application/octet-stream", row.filename or "file"

"""Idea attachment uploads (plan sprint-5/15 B1, AC-15-14..19).

An operator or embed user uploads a file onto an idea: sniffed by magic bytes
(the declared type is ignored), stored in the tenant's storage under
``ideation/ideas/<idea_id>/<attachment_id>``, recorded on ``idea_attachments``.
Every lookup is tenant-scoped (idea AND attachment resolved WITH ``tenant_id``).
"""
import re
import uuid
from typing import Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.storage import storage_for_tenant
from app.uploads import detect_attachment_mime

from ..models import Idea, IdeaAttachment
from ..schemas import IdeaAttachmentOut


# Refuse an upload once an idea already carries this many attachments.
MAX_ATTACHMENTS_PER_IDEA = 20
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

    def upload(
        self,
        tenant_id: str,
        idea_id: str,
        filename: str,
        content: bytes,
        *,
        content_prefix: str = "/ideation/ideas",
    ) -> IdeaAttachmentOut:
        idea = (
            self.db.query(Idea.id)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        mime = detect_attachment_mime(content, filename)
        if mime is None:
            raise HTTPException(415, "This file type is not supported.")
        existing = (
            self.db.query(func.count(IdeaAttachment.id))
            .filter(IdeaAttachment.idea_id == idea_id, IdeaAttachment.tenant_id == tenant_id)
            .scalar()
        )
        if (existing or 0) >= MAX_ATTACHMENTS_PER_IDEA:
            raise HTTPException(422, "This idea has reached its attachment limit.")
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

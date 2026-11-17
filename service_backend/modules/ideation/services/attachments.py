"""Idea attachment uploads (plan sprint-5/15 B1, AC-15-14..19).

An operator or embed user uploads a file onto an idea: sniffed by magic bytes
(the declared type is ignored), stored in the tenant's storage under
``ideation/ideas/<idea_id>/<attachment_id>``, recorded on ``idea_attachments``.
Every lookup is tenant-scoped (idea AND attachment resolved WITH ``tenant_id``).
"""
import io
import logging
import re
import uuid
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .history import HistoryActor

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.services.storage import storage_for_tenant
from app.uploads import detect_attachment_mime

from ..models import Idea, IdeaAttachment, IdeaComment
from ..schemas import IdeaAttachmentOut


# Refuse an upload once an idea already carries this many attachments (report
# AND comment files together) / a comment this many.
MAX_ATTACHMENTS_PER_IDEA = 50
MAX_ATTACHMENTS_PER_COMMENT = 10
# Tiles never load the original: an image gets a small preview, made lazily on
# the first ``?variant=thumb`` read (which is also the backfill for old rows).
THUMB_VARIANT = "thumb"
THUMB_MAX_SIDE = 320
THUMB_SOURCE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_THUMB_READ_CAP = 26 * 1024 * 1024
# An image whose decode would exceed this many pixels is never decoded (a 656 KB
# PNG can claim 13000x13000 and cost gigabytes of memory). A JPEG is measured
# after its reduced-scale decode, so a full-size 48 MP phone photo still previews.
THUMB_MAX_SOURCE_PIXELS = 40_000_000
# ``thumb_key == ""`` = "no preview": a refused or undecodable image, remembered
# so later reads answer 404 without touching storage. NULL = not tried yet.
NO_PREVIEW = ""


class _ThumbRefused(Exception):
    """The image cannot (or must not) be previewed."""
_log = logging.getLogger(__name__)
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
        actor: Optional["HistoryActor"] = None,
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
        # Files of a deleted comment are hidden, so they never use up the limit.
        existing = (
            self.db.query(func.count(IdeaAttachment.id))
            .outerjoin(
                IdeaComment,
                and_(IdeaComment.id == IdeaAttachment.comment_id, IdeaComment.tenant_id == tenant_id),
            )
            .filter(
                IdeaAttachment.idea_id == idea_id,
                IdeaAttachment.tenant_id == tenant_id,
                or_(IdeaAttachment.comment_id.is_(None), IdeaComment.deleted_at.is_(None)),
            )
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
        # The item's History tab (lane FEEDBACK-SUBSCRIBE).
        from . import history

        history.record(
            self.db, tenant_id, idea_id, history.ACTION_ATTACHMENT_ADDED, actor or history.HistoryActor(),
            to_value=name,
        )
        self.db.commit()
        return self.to_out(row, content_prefix)

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
        self,
        tenant_id: str,
        idea_id: str,
        attachment_id: str,
        variant: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """``(storage_key, mime, filename)`` of an uploaded attachment; 404 when it
        is outside the tenant/idea or is a URL-backed capture (no stored bytes).
        ``variant="thumb"`` serves the small preview instead (generated on first
        use; 404 when the file is not a decodable image)."""
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
        if variant == THUMB_VARIANT:
            if row.thumb_key == NO_PREVIEW:
                raise HTTPException(404, "No preview.")
            key = row.thumb_key or self._make_thumb(tenant_id, row)
            return key, "image/png" if key.endswith(".png") else "image/jpeg", "preview"
        return row.storage_key, row.mime or "application/octet-stream", row.filename or "file"

    def _make_thumb(self, tenant_id: str, row: IdeaAttachment) -> str:
        """Generate + store the preview of an image row (404 for anything else,
        including a corrupt image or a decompression bomb - never a 500)."""
        from app.services.storage import read_object

        if (row.mime or "") not in THUMB_SOURCE_MIMES:
            raise HTTPException(404, "No preview.")
        storage = storage_for_tenant(self.db, tenant_id)
        try:
            data = read_object(storage, row.storage_key, max_bytes=_THUMB_READ_CAP)
        except Exception as exc:  # noqa: BLE001 - storage hiccup: not remembered, retry later
            _log.info("thumbnail source unreadable for %s: %s", row.id, type(exc).__name__)
            raise HTTPException(404, "No preview.")
        try:
            content, mime = _render_thumb(data)
        except Exception as exc:  # noqa: BLE001 - corrupt / oversize image: remember it
            _log.info("thumbnail not generated for %s: %s", row.id, type(exc).__name__)
            row.thumb_key = NO_PREVIEW
            self.db.commit()
            raise HTTPException(404, "No preview.")
        ext = "png" if mime == "image/png" else "jpg"
        key = storage.save(f"ideation/ideas/{row.idea_id}/{row.id}.thumb.{ext}", content, mime)
        row.thumb_key = key
        self.db.commit()
        return key

    # ---- delete ------------------------------------------------------------

    def purge_for_idea(self, tenant_id: str, idea_id: str) -> List[str]:
        """Delete every attachment row of an idea (report AND comment files) and
        return their blob keys. No commit - the caller deletes the blobs with
        :meth:`delete_blobs` AFTER its commit."""
        rows = (
            self.db.query(IdeaAttachment)
            .filter(IdeaAttachment.idea_id == idea_id, IdeaAttachment.tenant_id == tenant_id)
            .all()
        )
        keys = [k for r in rows for k in (r.storage_key, r.thumb_key) if k]
        for r in rows:
            self.db.delete(r)
        self.db.flush()
        return keys

    def delete_blobs(self, tenant_id: str, keys: Iterable[str]) -> None:
        """Best-effort blob removal (a storage hiccup must not undo a delete)."""
        keys = list(keys)
        if not keys:
            return
        storage = storage_for_tenant(self.db, tenant_id)
        for key in keys:
            try:
                storage.delete(key)
            except Exception:  # noqa: BLE001
                _log.warning("could not delete attachment blob %s", key)


def _render_thumb(data: bytes) -> Tuple[bytes, str]:
    """``(bytes, mime)`` of the preview: fits 320x320, EXIF-rotated, JPEG (PNG when
    it has transparency). The size is read from the header and an image over
    ``THUMB_MAX_SOURCE_PIXELS`` (a JPEG: at its reduced ``draft`` scale) is refused
    BEFORE any decode; the small result is rotated, never the original.
    Pillow's own decompression-bomb guard stays on."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as opened:
        if opened.format == "JPEG":
            # Decode at reduced scale (up to 1/8): the limit below applies to
            # the size actually decoded, so a full-size phone photo previews.
            opened.draft("RGB", (640, 640))
        width, height = opened.size
        if width * height > THUMB_MAX_SOURCE_PIXELS:
            raise _ThumbRefused("too many pixels")
        opened.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE))
        img = ImageOps.exif_transpose(opened)
        alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        out = io.BytesIO()
        if alpha:
            img.convert("RGBA").save(out, "PNG")
            return out.getvalue(), "image/png"
        img.convert("RGB").save(out, "JPEG", quality=80)
        return out.getvalue(), "image/jpeg"

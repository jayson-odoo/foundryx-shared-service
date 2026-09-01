"""Legacy ``media_url`` → ``media_key`` backfill (sprint-4/10 Slice 3, AC-10-20).

Pre-plan-12 omnichannel media was stored as a full public/CDN URL in
``conversation_messages.media_url``. Plan 12 switched to storage KEYS
(``media_key``) so media resolves through the connection that wrote it and rides
the generic storage migration. This one-time backfill converts every remaining
``media_url``-only row: fetch the bytes (local-disk path when the URL points at
this deployment's ``/omnichannel/media/`` route, else an HTTP GET) →
``storage_for_tenant(...).save(...)`` → set ``media_key``, clear ``media_url``.

**Idempotent** (only rows with ``media_url`` set + ``media_key`` NULL are
touched - a re-run is a no-op) · **batched/capped** · **failure-isolated per
row** (a row whose blob can't be fetched is logged + skipped, never fails the
whole backfill, and stays convertible on a later run).

Exposed as a plain callable so both the per-module Alembic data migration AND
the tests can invoke it directly (conftest uses ``create_all`` - module Alembic
is a Postgres-only no-op there, so the function is the tested unit).
"""
from __future__ import annotations

import logging
import mimetypes
import os
import urllib.request
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

from sqlalchemy import and_
from sqlalchemy.orm import Session

logger = logging.getLogger("foundryx.omnichannel.backfill")

_MEDIA_ROUTE = "/omnichannel/media/"
# Cap a single blob read so a corrupt/huge legacy asset never balloons memory.
_MAX_BYTES = 25 * 1024 * 1024
_HTTP_TIMEOUT = 20  # seconds


@dataclass
class BackfillResult:
    converted: int = 0
    skipped: int = 0
    scanned: int = 0


def _fetch_bytes(media_url: str) -> tuple[bytes, Optional[str]]:
    """Return ``(content, mime)`` for a legacy media URL. Prefers a local-disk
    read when the URL points at this deployment's media route; falls back to an
    HTTP GET (CDN / external host). Raises on failure (caller isolates)."""
    from app.services.storage import LocalDiskStorage

    parsed = urlparse(media_url)
    # Local deployment media: ``…/omnichannel/media/<rel>`` → read from disk.
    if _MEDIA_ROUTE in parsed.path:
        rel = unquote(parsed.path.split(_MEDIA_ROUTE, 1)[1])
        if rel:
            try:
                return LocalDiskStorage().fetch(rel)
            except FileNotFoundError:
                pass  # fall through to HTTP (URL may be an external mirror)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported media_url scheme: {media_url!r}")

    req = urllib.request.Request(media_url, headers={"User-Agent": "Foundryx-Backfill/1.0"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310 - trusted own URLs
        content = resp.read(_MAX_BYTES + 1)
        if len(content) > _MAX_BYTES:
            raise ValueError("media exceeds the backfill size cap")
        mime = resp.headers.get_content_type() if resp.headers else None
    return content, mime


def _key_hint(media_url: str) -> str:
    name = os.path.basename(urlparse(media_url).path) or "media"
    # Strip the uuid suffix/extension noise - save() re-mints its own uuid.
    return unquote(name).rsplit(".", 1)[0][:64] or "media"


def backfill_media_urls(
    db: Session, *, batch_size: int = 200, limit: Optional[int] = None
) -> BackfillResult:
    """Convert legacy ``media_url`` rows to ``media_key`` (see module docstring).
    Returns counts. Commits per batch so partial progress survives an interrupt.
    """
    from app.services.storage import storage_for_tenant

    from .models import ConversationMessage

    result = BackfillResult()
    # Ids of rows we couldn't fetch - excluded so they don't clog the ordered
    # window and starve convertible rows behind them (progress is guaranteed).
    skipped_ids: list[str] = []
    while True:
        filters = [
            ConversationMessage.media_url.isnot(None),
            ConversationMessage.media_url != "",
            ConversationMessage.media_key.is_(None),
        ]
        if skipped_ids:
            filters.append(~ConversationMessage.id.in_(skipped_ids))
        rows = (
            db.query(ConversationMessage)
            .filter(and_(*filters))
            .order_by(ConversationMessage.created_at.asc())
            .limit(batch_size)
            .all()
        )
        if not rows:
            break

        for row in rows:
            result.scanned += 1
            if limit is not None and result.converted >= limit:
                db.commit()
                return result
            try:
                content, mime = _fetch_bytes(row.media_url)
                mime = row.media_mime or mime or (
                    mimetypes.guess_type(row.media_url)[0] or "application/octet-stream"
                )
                key = storage_for_tenant(db, row.tenant_id).save(
                    _key_hint(row.media_url), content, mime
                )
                row.media_key = key
                row.media_mime = row.media_mime or mime
                row.media_url = None
                result.converted += 1
            except Exception as exc:  # noqa: BLE001 - per-row isolation
                logger.warning(
                    "media_url backfill skipped message %s: %s", row.id, exc
                )
                result.skipped += 1
                skipped_ids.append(row.id)

        db.commit()

    return result

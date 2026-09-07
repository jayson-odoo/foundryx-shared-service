"""Migration media fetch (plan 33 S4, D-A6-7, AC-MIG-39/40/45).

ONE fetch -> sniff -> cap -> store pipeline for every media URL a migrated
message owes: the PRIMARY case (an `attachment` message, kind already known
from `message_type` via S3's `payload_json.migration.pendingMedia` flag) AND
the NESTED cases S3 deliberately left unflagged (`email`/`whatsapp_template`
media - see `migration_writer._map_message_content`'s own comment) where the
kind is unknown up front and only resolves after sniffing the real bytes.

Mirrors `inbound_service._store_media`'s own pattern (sniff, cap,
`storage_for_tenant().save`, continue on failure) with one difference: the
source is an arbitrary external URL from a two-year-old vendor record, not a
Graph media id - so it is re-validated through the SAME SSRF guard every
consumer webhook delivery uses (`webhook_service.assert_deliverable`, public
https only) immediately before every fetch (this branch has no
`app/services/url_guard.py` - that module does not exist here; the module's
own guard is the documented substitute the coder brief names).

Every failure returns `MediaFetchResult(ok=False, reason=...)` - this
function NEVER raises for a fetch/sniff/cap/storage problem (D-A6-7: the
message row survives regardless, the caller just doesn't get a `media_key`).
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.services.storage import storage_for_tenant
from app.uploads import detect_upload_mime

from .media_pipeline import ACCEPTED_MIMES
from .media_settings_service import MediaSettingsService
from .webhook_service import WebhookError, assert_deliverable

logger = logging.getLogger("foundryx.omnichannel.migration")

FETCH_TIMEOUT_SECONDS = 30.0

# mime -> kind, reverse of `ACCEPTED_MIMES` - used ONLY when the caller has no
# `declared_kind` up front (the nested email/template cases): the real kind is
# whatever the sniffed mime maps to, defaulting to DOCUMENT (the most
# permissive/generic category) for a mime `ACCEPTED_MIMES` does not carry at
# all rather than rejecting outright - the whole point of sniffing here is to
# classify an unknown attachment, not to gate it against a fixed vocabulary
# the way live outbound sends do.
_MIME_TO_KIND = {}
for _kind, _mimes in ACCEPTED_MIMES.items():
    for _mime in _mimes:
        _MIME_TO_KIND.setdefault(_mime, _kind)


@dataclass
class MediaFetchResult:
    ok: bool
    key: Optional[str] = None
    mime: Optional[str] = None
    size: Optional[int] = None
    filename: Optional[str] = None
    reason: Optional[str] = None  # set iff ok is False


def _default_client_factory() -> httpx.Client:
    return httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)


# The test seam - a MODULE-LEVEL name (like `RespondIoClient.from_connection`),
# never the bare `httpx.Client` symbol: `httpx` is a SHARED module object, so
# monkeypatching `httpx.Client` directly would silently redirect every OTHER
# httpx consumer in the same test process (the respond.io API client's own
# transport included) onto this test's media stub. `monkeypatch.setattr(
# migration_media, "_client_factory", ...)` scopes the override to this
# module alone.
_client_factory = _default_client_factory


def fetch_and_store_media(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    message_id: str,
    url: str,
    filename: Optional[str],
    declared_kind: Optional[str],
    http_client: Optional[httpx.Client] = None,
) -> MediaFetchResult:
    """Fetch `url` (capped read, sniffed, cap-checked by resolved kind) and
    store it via `storage_for_tenant`. `declared_kind` is the message's own
    `message_type` when it is one of IMAGE/VIDEO/AUDIO/DOCUMENT (the PRIMARY
    `attachment` case - the sniffed mime is then required to belong to that
    declared kind's accepted set, a "sniff mismatch" reject otherwise);
    `None` for the nested email/template cases, where the kind is resolved
    FROM the sniffed mime instead. `http_client` is an explicit per-call
    override; tests normally swap `_client_factory` instead (see above)."""
    if not url:
        return MediaFetchResult(ok=False, reason="No source URL was recorded for this media.")

    try:
        assert_deliverable(url)
    except WebhookError as exc:
        return MediaFetchResult(ok=False, reason=f"Source URL rejected: {exc}")

    settings_svc = MediaSettingsService(db)
    # The read is bounded by the workspace's LARGEST configured cap (DOCUMENT)
    # regardless of kind - this is what keeps a hostile/oversized response body
    # from ever buffering past the biggest limit this workspace allows, before
    # the real per-kind cap (resolved AFTER sniffing) is checked below.
    read_cap = settings_svc.max_bytes_for(tenant_id, workspace_id, "DOCUMENT")

    owns_client = http_client is None
    client = http_client or _client_factory()
    content = bytearray()
    try:
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return MediaFetchResult(ok=False, reason=f"Source returned HTTP {resp.status_code}.")
                for chunk in resp.iter_bytes():
                    content.extend(chunk)
                    if len(content) > read_cap:
                        return MediaFetchResult(
                            ok=False, reason=f"Media exceeds the workspace's byte cap ({read_cap} bytes)."
                        )
        except httpx.TimeoutException:
            return MediaFetchResult(ok=False, reason="Timed out fetching source media.")
        except httpx.HTTPError as exc:
            return MediaFetchResult(ok=False, reason=f"Could not fetch source media: {exc}")
    finally:
        if owns_client:
            client.close()

    content_bytes = bytes(content)
    if not content_bytes:
        return MediaFetchResult(ok=False, reason="The fetched media was empty.")

    mime = detect_upload_mime(content_bytes, filename)
    if mime is None:
        return MediaFetchResult(ok=False, reason="Could not verify the media's file type.")

    resolved_kind = (declared_kind or "").upper()
    if resolved_kind and resolved_kind in ACCEPTED_MIMES:
        if mime not in ACCEPTED_MIMES[resolved_kind]:
            return MediaFetchResult(
                ok=False,
                reason=(
                    f"The declared type ({resolved_kind.lower()}) does not match the "
                    "file's real content."
                ),
            )
    else:
        resolved_kind = _MIME_TO_KIND.get(mime, "DOCUMENT")

    kind_cap = settings_svc.max_bytes_for(tenant_id, workspace_id, resolved_kind)
    if len(content_bytes) > kind_cap:
        return MediaFetchResult(
            ok=False,
            reason=(
                f"File is {len(content_bytes)} bytes; the {resolved_kind.lower()} "
                f"limit is {kind_cap} bytes."
            ),
        )

    try:
        key = storage_for_tenant(db, tenant_id).save(
            f"omnichannel/migration/{tenant_id}/{message_id}", content_bytes, mime
        )
    except Exception as exc:  # noqa: BLE001 - storage hiccup, never abort the run
        logger.exception("migration media store failed for message %s", message_id)
        return MediaFetchResult(ok=False, reason=f"Storage failed: {exc}")

    return MediaFetchResult(ok=True, key=key, mime=mime, size=len(content_bytes), filename=filename)

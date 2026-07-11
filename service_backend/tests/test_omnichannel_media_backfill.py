"""Legacy ``media_url`` → ``media_key`` backfill (sprint-4/10 Slice 3, AC-10-20).

Conftest uses ``create_all`` (module Alembic is a Postgres-only no-op here), so
the backfill FUNCTION is the tested unit — seed a ``media_url``-only row, run it,
assert the row is now key-based + the URL is cleared. Also covers idempotency
and per-row failure-isolation (an unfetchable blob is skipped, not fatal).
"""
import pytest

from app.models import DEFAULT_TENANT_ID


@pytest.fixture
def media_root(tmp_path):
    from app.config import settings
    from app.services.storage import clear_adapter_cache

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    clear_adapter_cache()
    try:
        yield tmp_path
    finally:
        settings.media_root = prev


def _seed_message(db, *, media_url, media_mime=None, media_key=None):
    from modules.omnichannel.models import Contact, ConversationMessage, Workspace

    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="WS", is_default=True)
    db.add(ws)
    db.flush()
    contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, phone="+100")
    db.add(contact)
    db.flush()
    msg = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact.id,
        sender_type="CONTACT",
        message_type="image",
        media_url=media_url,
        media_mime=media_mime,
        media_key=media_key,
    )
    db.add(msg)
    db.commit()
    return msg.id


def test_backfill_converts_local_media_url_to_key(session_factory, media_root):
    from modules.omnichannel.backfill import backfill_media_urls
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    # A legacy blob physically on disk under the media route.
    rel = "legacy/pic-abc123.png"
    (media_root / "legacy").mkdir(parents=True)
    (media_root / rel).write_bytes(b"PNGDATA")
    msg_id = _seed_message(
        db,
        media_url=f"http://localhost:8001/omnichannel/media/{rel}",
        media_mime="image/png",
    )

    result = backfill_media_urls(db)

    assert result.converted == 1
    assert result.skipped == 0
    row = db.get(ConversationMessage, msg_id)
    assert row.media_key  # now key-based
    assert row.media_url is None  # legacy URL cleared
    assert row.media_mime == "image/png"
    # No storage connection in the test tenant → local-disk raw key that fetches
    # back the original bytes.
    from app.services.storage import storage_for_tenant

    content, _ = storage_for_tenant(db, DEFAULT_TENANT_ID).fetch(row.media_key)
    assert content == b"PNGDATA"
    db.close()


def test_backfill_is_idempotent(session_factory, media_root):
    from modules.omnichannel.backfill import backfill_media_urls

    db = session_factory()
    rel = "a/one.png"
    (media_root / "a").mkdir(parents=True)
    (media_root / rel).write_bytes(b"X")
    _seed_message(db, media_url=f"http://x/omnichannel/media/{rel}")

    first = backfill_media_urls(db)
    second = backfill_media_urls(db)  # nothing left to convert

    assert first.converted == 1
    assert second.converted == 0
    assert second.scanned == 0
    db.close()


def test_backfill_skips_unfetchable_row_without_failing(session_factory, media_root):
    from modules.omnichannel.backfill import backfill_media_urls
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    # Points at a missing local blob AND an unsupported scheme → un-fetchable.
    bad_id = _seed_message(db, media_url="ftp://nowhere/omnichannel/media/missing.png")
    # A convertible row BEHIND the skipped one — must still be reached.
    rel = "b/good.png"
    (media_root / "b").mkdir(parents=True)
    (media_root / rel).write_bytes(b"OK")
    good_id = _seed_message(db, media_url=f"http://x/omnichannel/media/{rel}")

    result = backfill_media_urls(db, batch_size=1)

    assert result.converted == 1
    assert result.skipped == 1
    bad = db.get(ConversationMessage, bad_id)
    good = db.get(ConversationMessage, good_id)
    assert bad.media_key is None and bad.media_url is not None  # left for a later retry
    assert good.media_key and good.media_url is None
    db.close()


def test_media_sample_key_registered_and_drift_clean():
    """AC-10-20 + AC-10-07: whatsapp_templates.media_sample_key is registered and
    the drift test (media_sample_key no longer excluded) passes."""
    from app.database import Base
    from app.storage_migration.core_locations import ensure_core_locations
    from app.storage_migration.registry import (
        all_key_columns,
        registered_scalar_columns,
    )
    from modules.omnichannel import models as _omni  # noqa: F401 — populate metadata
    from modules.omnichannel.bootstrap import register_engine_entities
    from modules.omnichannel.db import OmniBase

    ensure_core_locations()
    register_engine_entities()

    registered = registered_scalar_columns()
    assert ("whatsapp_templates", "media_sample_key") in registered
    unregistered = all_key_columns([Base.metadata, OmniBase.metadata]) - registered
    assert not unregistered, f"Unregistered storage-key columns: {sorted(unregistered)}"

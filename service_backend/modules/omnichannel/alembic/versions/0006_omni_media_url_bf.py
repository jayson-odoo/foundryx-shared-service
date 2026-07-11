"""omnichannel sprint-4/10 Slice 3 — legacy ``media_url`` → ``media_key`` backfill.

Data-only. Converts every pre-plan-12 ``conversation_messages`` row that still
carries a legacy ``media_url`` (and no ``media_key``) to a storage KEY so its
media resolves by-connection and rides the generic storage migration. The real
work lives in ``modules.omnichannel.backfill.backfill_media_urls`` (idempotent,
per-row failure-isolated, unit-tested against SQLite); this migration just
invokes it on the live connection. Failure-isolated at the migration level too —
a backfill hiccup must never block the module's migration chain.

Revision ID: 0006_omni_media_url_bf
Revises: 0005_omni_reactions
Create Date: 2026-07-11
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

revision = "0006_omni_media_url_bf"
down_revision = "0005_omni_reactions"
branch_labels = None
depends_on = None

logger = logging.getLogger("foundryx.omnichannel.backfill")


def upgrade() -> None:
    from app.config import settings
    from modules.omnichannel.backfill import backfill_media_urls

    # Run on a SEPARATE engine/connection — NOT ``op.get_bind()``. The backfill
    # commits per batch (crash-safe partial progress); committing Alembic's own
    # migration connection mid-run would corrupt the ``alembic_version`` stamp
    # (reviewer blocker). This revision alters no schema, so the rows read on the
    # side connection are already-committed data (no contention with Alembic's
    # open transaction). Failure-isolated at the migration level too — a backfill
    # hiccup must never block the module's migration chain.
    engine = create_engine(settings.database_url)
    session = Session(bind=engine)
    try:
        result = backfill_media_urls(session)
        logger.info(
            "media_url backfill: converted=%s skipped=%s scanned=%s",
            result.converted,
            result.skipped,
            result.scanned,
        )
    except Exception as exc:  # noqa: BLE001 — never block the migration chain
        logger.warning("media_url backfill failed (non-fatal): %s", exc)
        session.rollback()
    finally:
        session.close()
        engine.dispose()


def downgrade() -> None:
    # Irreversible data conversion — the legacy media_url is intentionally not
    # reconstructable from a media_key (keys don't carry the old public URL).
    pass

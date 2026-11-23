"""`channel.updated` consumer webhook event (Track A S9): opt-in, so only an
endpoint that lists it in its `events` receives it.

Emitted after a channel's state changed (connect, pause/resume, disconnect,
restore, the token check marking or clearing ERROR, a token replace). The
body is `{"channel": <GET /channels item>}`, built per endpoint payload
version (version 2 adds `connectionState`). Failure-isolated: a webhook
problem never fails the change that triggered it.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Channel

logger = logging.getLogger(__name__)

EVENT_TYPE = "channel.updated"


def emit_channel_updated(db: Session, channel: Channel) -> None:
    """Queue `channel.updated` for ``channel`` (already committed)."""
    channel_id = getattr(channel, "id", None)
    try:
        from .public_gateway_service import PublicGatewayService
        from .webhook_delivery import enqueue_event

        gateway = PublicGatewayService(db)

        def data():  # built per endpoint payload version, see `_fan_out`
            return {"channel": gateway.public_channel_item(channel).model_dump(mode="json")}

        stamp = int(datetime.now(timezone.utc).timestamp())
        event_id = f"{channel.id}:channel:{stamp}:{uuid.uuid4().hex[:8]}"
        enqueue_event(db, channel, EVENT_TYPE, event_id, data)
    except Exception:  # noqa: BLE001 - a webhook bug must never break a channel change
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("rollback after channel.updated failure failed")
        logger.exception("channel.updated enqueue failed for channel %s", channel_id)

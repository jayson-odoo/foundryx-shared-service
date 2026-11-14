"""Meta webhook change-handler registry - CORE since plan 64 (D5, review R2).

Meta delivers every webhook of the ONE app to ONE callback (omnichannel's
ingress). Page ``changes[]`` items such as ``leadgen`` belong to other
Services, and must reach them even when the Page has no omnichannel channel
or omnichannel is inactive for the tenant. A Service claims an
``(object, field)`` pair here at boot; omnichannel's ``InboundService``
dispatches every matching ``entry[].changes[]`` item FIRST, before it resolves
a channel.

Rules (same shape as ``app/module_platform/public_cors.py``):
- One owner per ``(object, field)``; a second module claiming it is a loud
  boot error. Re-registering by the same module is idempotent.
- A handler gets ``(db, object, entry_id, change_value)`` and must only
  enqueue (the webhook worker has no tenant context yet).
- A handler exception is logged and isolated: it never affects omnichannel's
  processing of the same payload or the other handlers.
- With nothing registered, dispatch does nothing at all.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# (db, object, entry_id, change_value) -> None
MetaChangeHandler = Callable[[Session, str, str, Any], None]


class DuplicateMetaChangeHandler(Exception):
    """Two modules claimed the same Meta (object, field) at boot - fatal."""


@dataclass(frozen=True)
class MetaChangeRegistration:
    object: str
    field: str
    provider_module: str
    handler: MetaChangeHandler


_HANDLERS: Dict[Tuple[str, str], MetaChangeRegistration] = {}


def register_meta_change_handler(
    object: str, field: str, provider_module: str, handler: MetaChangeHandler
) -> None:
    """Boot-time registration; idempotent per ((object, field), module)."""
    key = (object, field)
    existing = _HANDLERS.get(key)
    if existing is not None and existing.provider_module != provider_module:
        raise DuplicateMetaChangeHandler(
            f"Meta change {object!r}/{field!r} already owned by "
            f"'{existing.provider_module}'; '{provider_module}' conflicts."
        )
    _HANDLERS[key] = MetaChangeRegistration(object, field, provider_module, handler)


def reset_meta_change_handlers() -> None:
    """Test hook - clear the registry between boot simulations."""
    _HANDLERS.clear()


def meta_change_handlers() -> List[MetaChangeRegistration]:
    return list(_HANDLERS.values())


def meta_change_handler(object: str, field: str) -> Optional[MetaChangeRegistration]:
    return _HANDLERS.get((object, field))


def dispatch_meta_changes(db: Session, payload: Any) -> int:
    """Hand every ``entry[].changes[]`` item with a registered owner to that
    owner. Returns how many handlers ran without raising. Never raises; a
    malformed payload is simply "nothing to dispatch"."""
    if not _HANDLERS or not isinstance(payload, dict):
        return 0
    obj = payload.get("object")
    entries = payload.get("entry")
    if not isinstance(obj, str) or not isinstance(entries, list):
        return 0
    handled = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        raw_id = entry.get("id")
        entry_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("field"), str):
                continue
            reg = _HANDLERS.get((obj, change["field"]))
            if reg is None:
                continue
            try:
                reg.handler(db, obj, entry_id, change.get("value"))
                handled += 1
            except Exception:  # noqa: BLE001 - one Service's handler never breaks the ingress.
                logger.exception(
                    "Meta change handler %s for %s/%s failed (entry %s)",
                    reg.provider_module, obj, change["field"], entry_id,
                )
                _recover_session(db)
    return handled


def _recover_session(db: Session) -> None:
    """A handler that failed mid-flush leaves the session needing a rollback;
    only then roll back, so a clean session's pending work is untouched."""
    try:
        if not db.is_active:
            db.rollback()
    except Exception:  # noqa: BLE001
        logger.exception("session recovery after a Meta change handler failure failed")

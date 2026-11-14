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
- A module may also RESERVE further pairs it consumes itself without a
  handler (``reserve_meta_change_fields``).
- A handler gets ``(db, object, entry_id, change_value)`` and must only
  enqueue (the webhook worker has no tenant context yet). It maps the Page or
  account to its tenant(s) from ``entry_id`` against its own live bindings,
  never from ids inside ``change_value`` (raw Meta data).
- Handlers MUST be idempotent (e.g. dedupe on ``leadgen_id``): the inbound
  task retries the whole payload when omnichannel's own processing fails, so
  the same change can be dispatched more than once.
- Each handler runs in its own SAVEPOINT: on an exception its writes are
  rolled back, the error is logged, and omnichannel's processing of the same
  payload (and the other handlers) carries on. A successful handler's writes
  are committed straight away (the ingress may stop early or roll back later).
- Message traffic omnichannel parses itself is reserved here in core
  (``RESERVED_OBJECTS`` / ``RESERVED_FIELDS``); any other module claiming it
  fails at boot.
- With nothing registered, dispatch does nothing at all.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
    handler: Optional[MetaChangeHandler]  # None = reserved, consumed by the owner itself


_HANDLERS: Dict[Tuple[str, str], MetaChangeRegistration] = {}

# Webhook traffic omnichannel's ingress parses itself, reserved IN CORE so the
# claim exists before ANY module boots (a module discovered before omnichannel
# can never take it, and a conflict always fails the claimant, never
# omnichannel). Every field of a WhatsApp Business Account belongs to
# omnichannel (its parser reads `value.messages`/`statuses` on any field);
# Page / Instagram messaging fields too.
_OMNICHANNEL = "omnichannel"
RESERVED_OBJECTS: Dict[str, str] = {"whatsapp_business_account": _OMNICHANNEL}
RESERVED_FIELDS: Dict[Tuple[str, str], str] = {
    (obj, field): _OMNICHANNEL
    for obj in ("page", "instagram")
    for field in (
        "messages",
        "messaging_postbacks",
        "message_reads",
        "message_deliveries",
        "message_reactions",
        "message_echoes",
    )
}


def _reserved_owner(object: str, field: str) -> Optional[str]:
    return RESERVED_OBJECTS.get(object) or RESERVED_FIELDS.get((object, field))


def register_meta_change_handler(
    object: str, field: str, provider_module: str, handler: MetaChangeHandler
) -> None:
    """Boot-time registration; idempotent per ((object, field), module)."""
    key = (object, field)
    reserved_by = _reserved_owner(object, field)
    if reserved_by is not None and reserved_by != provider_module:
        raise DuplicateMetaChangeHandler(
            f"Meta change {object!r}/{field!r} is reserved by '{reserved_by}'; "
            f"'{provider_module}' cannot claim it."
        )
    existing = _HANDLERS.get(key)
    if existing is not None and existing.provider_module != provider_module:
        raise DuplicateMetaChangeHandler(
            f"Meta change {object!r}/{field!r} already owned by "
            f"'{existing.provider_module}'; '{provider_module}' conflicts."
        )
    _HANDLERS[key] = MetaChangeRegistration(object, field, provider_module, handler)


def reserve_meta_change_fields(object: str, fields: Iterable[str], provider_module: str) -> None:
    """Claim ``(object, field)`` pairs a module consumes itself (no handler is
    dispatched for them). Same one-owner rule as a handler registration."""
    for field in fields:
        key = (object, field)
        reserved_by = _reserved_owner(object, field)
        if reserved_by is not None and reserved_by != provider_module:
            raise DuplicateMetaChangeHandler(
                f"Meta change {object!r}/{field!r} is reserved by '{reserved_by}'; "
                f"'{provider_module}' cannot claim it."
            )
        existing = _HANDLERS.get(key)
        if existing is not None and existing.provider_module != provider_module:
            raise DuplicateMetaChangeHandler(
                f"Meta change {object!r}/{field!r} already owned by "
                f"'{existing.provider_module}'; '{provider_module}' conflicts."
            )
        if existing is None:
            _HANDLERS[key] = MetaChangeRegistration(object, field, provider_module, None)


def reset_meta_change_handlers() -> None:
    """Test hook - clear the registry between boot simulations."""
    _HANDLERS.clear()


def meta_change_handlers() -> List[MetaChangeRegistration]:
    """Registrations that carry a handler (reservations excluded)."""
    return [r for r in _HANDLERS.values() if r.handler is not None]


def meta_change_handler(object: str, field: str) -> Optional[MetaChangeRegistration]:
    return _HANDLERS.get((object, field))


def dispatch_meta_changes(db: Session, payload: Any) -> int:
    """Hand every ``entry[].changes[]`` item with a registered owner to that
    owner. Returns how many handlers ran without raising. Never raises; a
    malformed payload is simply "nothing to dispatch"."""
    if not isinstance(payload, dict) or not any(r.handler for r in _HANDLERS.values()):
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
            if reg is None or reg.handler is None:
                continue
            if _run_isolated(db, reg, obj, entry_id, change.get("value")):
                handled += 1
    return handled


def _run_isolated(db: Session, reg: MetaChangeRegistration, obj: str, entry_id: str, value: Any) -> bool:
    """Run one handler inside a SAVEPOINT. On any exception the savepoint is
    rolled back (the handler's writes vanish, and on Postgres the outer
    transaction is NOT left aborted), the error is logged, and False is
    returned. Never raises an ``Exception``."""
    try:
        savepoint = db.begin_nested()
    except Exception:  # noqa: BLE001 - a broken session must not stop the ingress.
        logger.exception("could not open a savepoint for Meta change handler %s", reg.provider_module)
        return False
    try:
        reg.handler(db, obj, entry_id, value)
        if savepoint.is_active:
            savepoint.commit()
        # Commit NOW: omnichannel may return early without committing (no
        # channel for this Page, module inactive) or roll back / retry later,
        # and neither may lose what a successful handler enqueued.
        db.commit()
        return True
    except Exception:  # noqa: BLE001 - one Service's handler never breaks the ingress.
        logger.exception(
            "Meta change handler %s for %s/%s failed (entry %s)",
            reg.provider_module, obj, reg.field, entry_id,
        )
        try:
            if savepoint.is_active:
                savepoint.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("savepoint rollback after a Meta change handler failure failed")
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return False

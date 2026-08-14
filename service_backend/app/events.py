"""Minimal in-process event seam (sprint-2/01 §backend).

``emit("StatusTransitioned", payload)`` is fired by the status machine; the
Workflow engine (BL-025) subscribes later. Synchronous + in-process by design -
durability/async ride the payload's own primitives (e.g. the email outbox),
not this seam. Subscriber errors are logged, never propagated: a broken
listener must not abort the transition that already committed.
"""
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List

logger = logging.getLogger("foundryx.events")

EVENT_STATUS_TRANSITIONED = "StatusTransitioned"

_subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)


def subscribe(event: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    _subscribers[event].append(handler)


def unsubscribe(event: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    if handler in _subscribers[event]:
        _subscribers[event].remove(handler)


def emit(event: str, payload: Dict[str, Any]) -> None:
    for handler in list(_subscribers[event]):
        try:
            handler(payload)
        except Exception:  # noqa: BLE001 - listeners never break the emitter
            logger.exception("event subscriber failed for %s", event)

"""``EntitySink`` - the outbound seam (D6, plan §6).

Slice 1 stops at an **approved canonical record**. The sink interface is defined
now (so approval has a real boundary to call, and hop 2 has a real contract to
target) and ships with ONE implementation: a **logging sink** that records what
it WOULD have sent.

    !!  THE SLICE-1 SINK IS A DELIBERATE, TAGGED SEAM - NOT A CONSUMER.  !!

That distinction matters. A fake in-memory "consumer" that accepts records and
reports success would let the pipeline look finished while nothing had ever
crossed the network - the exact "mock left standing as done" failure the
Definition-of-Done gate exists to catch. So this sink is explicit about being a
no-op: it names itself in every result, writes an observable activity row, and
never claims a consumer accepted anything.

Real Sorento wiring (hop 2 - near-identity, since canonical is derived from
Sorento's own shapes) is a later slice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from .canonical.base import CanonicalRecord

logger = logging.getLogger("foundryx.autocount")

# The sink that actually delivered (or declined to). Stored on the result so an
# operator reading a pushed record can tell a real delivery from the slice-1
# no-op at a glance - never inferred from the absence of an error.
SINK_LOGGING = "logging"


@dataclass
class WriteResult:
    ok: bool
    sink: str
    # The consumer's id for the record, once a real consumer assigns one.
    external_id: Optional[str] = None
    message: str = ""
    # True when nothing actually left the process. The approval surface reads
    # this rather than guessing from ``ok``.
    delivered: bool = False
    #     !!  ``retryable`` AND ``failed`` NEED OPPOSITE HANDLING.  !!
    # The consumer's own verdict word, carried STRUCTURALLY rather than left
    # buried in ``message``: ``retryable`` means nothing was written and a
    # dependency is missing, so the record must be re-offered on the next
    # unattended run; ``failed`` means the DATA was rejected, so re-offering it
    # just re-fails forever and pins the task's health signal red. Empty for a
    # sink with no verdict vocabulary (the logging no-op).
    outcome: str = ""


class EntitySink(Protocol):
    """One entity, one company. Writes a canonical record OUT.

    The same interface serves hop 2 (canonical → consumer, slice 1+) and the
    AutoCount write path (canonical → AutoCount, slice 4) - both are "hand this
    canonical record to something outside the ESB".
    """

    name: str

    def write(self, record: CanonicalRecord, *, request_id: str) -> WriteResult: ...


class LoggingSink:
    """SLICE-1 SINK - records what it would have sent; delivers NOTHING.

    ``delivered=False`` on every result, always. That is the whole point: an
    approved record is provably a local state change until a real consumer sink
    is configured.
    """

    name = SINK_LOGGING

    def __init__(self) -> None:
        # Kept for the calling service to log/inspect within one push; not a
        # store, not a queue, and deliberately not persisted.
        self.written: List[Dict[str, Any]] = []

    def write(self, record: CanonicalRecord, *, request_id: str) -> WriteResult:
        payload = record.comparable()
        self.written.append(
            {
                "requestId": request_id,
                "identity": record.identity(),
                "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "payload": payload,
            }
        )
        logger.info(
            "[autocount sink:%s] would push %s (request %s) - slice-1 no-op sink, "
            "nothing was delivered to a consumer.",
            self.name,
            record.identity(),
            request_id,
        )
        return WriteResult(
            ok=True,
            sink=self.name,
            external_id=None,
            message=(
                "Recorded by the slice-1 logging sink - no consumer is wired yet, "
                "so nothing was delivered."
            ),
            delivered=False,
        )

    def delete_batch(self, source_refs: List[str], *, dry_run: bool = False) -> Dict[str, Any]:
        """Plan 22 S3 (AC-22-21) - a company with no real consumer wired still
        needs its reconcile delete intents to resolve to SOMETHING, or they
        would sit STAGED forever. Logged, never delivered (``deleted`` here
        means "handled locally", the same honesty ``write`` already carries
        for upserts) - the moment a real sink is configured the SAME refs
        route to it instead."""
        refs = [str(r) for r in source_refs if str(r or "").strip()]
        for ref in refs:
            logger.info(
                "[autocount sink:%s] would delete %s - slice-1 no-op sink, "
                "nothing was delivered to a consumer.",
                self.name,
                ref,
            )
        return {
            "dry_run": dry_run,
            "summary": {
                "total": len(refs), "deleted": len(refs),
                "deactivated": 0, "not_found": 0, "failed": 0,
            },
            "records": [{"source_ref": ref, "outcome": "deleted"} for ref in refs],
        }


# ── sink registry ─────────────────────────────────────────────────────────────
# Mirrors the source registry: chosen per entity, per company, by config. A
# Sorento sink registers here in a later slice and the pipeline is unchanged.

_SINKS: Dict[str, Any] = {}


class UnknownSinkImpl(Exception):
    """A configured sink has no registered factory. LOUD - falling back to the
    logging sink would silently stop delivering to a real consumer."""


def register_sink(name: str, factory) -> None:
    _SINKS[name] = factory


def sink_for(name: str) -> EntitySink:
    factory = _SINKS.get(name)
    if factory is None:
        raise UnknownSinkImpl(f"No AutoCount sink registered for '{name}'.")
    return factory()


register_sink(SINK_LOGGING, LoggingSink)

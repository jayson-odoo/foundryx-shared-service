"""Derived / computed status — dependency wiring (sprint-4/03 G2/G4/G7).

A ``DerivedTrigger`` maps a domain event (a CHILD changing, e.g. a payment, or
the owner ITSELF on created/updated/status_changed) to the owner records whose
AUTO edges should be re-evaluated. The bus subscriber (``_on_event``) fans every
committed domain event to the matching triggers and calls
``status_machine.reevaluate`` on each owner.

Run safety (G7): the subscriber rides the after-commit drain's isolated commit
(``_notify_subscribers``) — a broken/slow derivation is fully isolated and can
NEVER 500 the triggering write. Loop-safe: ``reevaluate`` tags the events its
own transitions emit with the DERIVED origin, which this subscriber skips, so an
auto transition can't infinitely re-enter. Fail-closed: a raising owner resolver
or reevaluate is logged + skipped, never a wrong-direction move.

SELF derivation is GENERIC (sprint-4/03): any unscoped, tenant-owned status
entity that declares a ``model`` re-evaluates its OWN auto edges on its own
created/updated/status_changed — authoring an auto edge in the UI is enough to
make it fire, no per-module wiring. CROSS-entity derivations (a CHILD changing
re-derives an OWNER — Cluster D participant Checked-in, Cluster F invoice
Paid/Overdue) still register an explicit ``DerivedTrigger`` + aggregate facts +
seed system auto-edges in their plans.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from sqlalchemy.orm import Session

logger = logging.getLogger("dreamz.status.derived")

# Events that can change a derived owner's facts. (deleted included so a removed
# child re-derives the owner, e.g. a refunded ticket dropping participant
# eligibility — the owner is resolved from the event payload, not the dead row.)
_REEVAL_ACTIONS = {"created", "updated", "status_changed", "deleted"}


@dataclass(frozen=True)
class DerivedTrigger:
    """Wiring from a triggering entity's events to the owner(s) to re-evaluate.

    ``resolve_owners(db, tenant_id, event) -> [owner records]`` is tenant-scoped
    by contract (resolve children/owners with the tenant filter). For a SELF
    trigger, ``trigger_entity == owner_entity`` and the resolver loads the owner
    by ``event['record_id']``.
    """

    owner_entity: str
    trigger_entity: str
    resolve_owners: Callable[[Session, str, Dict[str, Any]], List[Any]]


_TRIGGERS: List[DerivedTrigger] = []


def register_derived_trigger(trigger: DerivedTrigger) -> None:
    """Idempotent — mirrors ``register_status_entity`` (modules re-register on
    every bootstrap). Dedup by (owner_entity, trigger_entity)."""
    for existing in _TRIGGERS:
        if (
            existing.owner_entity == trigger.owner_entity
            and existing.trigger_entity == trigger.trigger_entity
        ):
            return
    _TRIGGERS.append(trigger)


def list_derived_triggers() -> List[DerivedTrigger]:
    return list(_TRIGGERS)


def _on_event(session: Session, ev: Dict[str, Any]) -> None:
    """Bus subscriber — re-evaluate the owners affected by ``ev``."""
    source = ev.get("source")
    if source and source.get("kind") == "derived":
        return  # our OWN re-eval write — never re-enter (G7 loop guard)
    if ev.get("action") not in _REEVAL_ACTIONS:
        return
    entity_type = ev.get("entity_type")
    tenant_id = ev.get("tenant_id")
    if not tenant_id:
        return

    from app.services.status_machine import reevaluate
    from app.status_engine.registry import get_status_entity

    seen: set = set()

    # Generic SELF re-evaluation (sprint-4/03): an unscoped, tenant-owned status
    # entity re-evaluates its OWN auto edges when its own record changes — no
    # per-module DerivedTrigger needed. Authoring an auto edge in the UI is enough
    # to make it fire (closes the foolproof-UI gap). Cross-entity (child -> owner)
    # derivations still register an explicit DerivedTrigger below.
    self_entity = get_status_entity(entity_type)
    if (
        self_entity is not None
        and not self_entity.scoped
        and not self_entity.platform_owned
        and self_entity.model is not None
    ):
        record_id = ev.get("record_id")
        try:
            record = self_entity.load_record(session, tenant_id, record_id)
        except Exception:  # noqa: BLE001 — fail-closed, never break the seam
            logger.exception("derived self load failed (%s %s)", entity_type, record_id)
            record = None
        if record is not None:
            seen.add((entity_type, record_id))
            try:
                reevaluate(session, entity_type, record, tenant_id=tenant_id)
            except Exception:  # noqa: BLE001 — never break the seam
                logger.exception(
                    "derived self reevaluate failed (%s %s)", entity_type, record_id
                )

    for trig in _TRIGGERS:
        if trig.trigger_entity != entity_type:
            continue
        try:
            owners = trig.resolve_owners(session, tenant_id, ev) or []
        except Exception:  # noqa: BLE001 — fail-closed, never break the seam
            logger.exception(
                "derived owner resolution failed (%s -> %s)",
                entity_type,
                trig.owner_entity,
            )
            continue
        for owner in owners:
            key = (trig.owner_entity, getattr(owner, "id", None))
            if key in seen:
                continue
            seen.add(key)
            try:
                reevaluate(session, trig.owner_entity, owner, tenant_id=tenant_id)
            except Exception:  # noqa: BLE001 — one bad owner never stops siblings
                logger.exception(
                    "derived reevaluate failed (%s %s)", trig.owner_entity, key[1]
                )


def install_derived_status() -> None:
    """Register the derived-status subscriber on the event bus. Idempotent —
    safe to call from app lifespan and any bootstrap path."""
    from app.workflow_engine.entity_events import register_event_subscriber

    register_event_subscriber(_on_event)

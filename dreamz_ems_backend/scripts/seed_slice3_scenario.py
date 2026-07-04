"""Runtime seed for Cluster D slice-3 manual testing (default tenant).

Run:  cd dreamz_ems_backend && source .venv/bin/activate && python -m scripts.seed_slice3_scenario

Does TWO things, both idempotent-ish (safe to re-run; event name is timestamped):

  1. Reseeds the canonical ticket status graph for the default tenant. The UI
     edits forked it to a Draft/Confirmed graph whose KEYS don't match the
     slice-3 code contract (issued/valid/checked_in/transferred/void/refunded),
     so `_status_id_by_key(TICKET_ENTITY, …, "issued")` returns None → 409 on
     scan/nominate. We delete the existing ticket Status rows + their edges (both
     the tenant fork AND any platform NULL-tier rows) and re-seed via the
     canonical `_seed_unscoped_graph`. Ticket lifecycle KEYS are a code contract.

  2. Seeds a fresh, valid, testable slice-3 scenario via the REAL services:
     a published GA offering, two profiles, a confirmed PAID ticket (mints
     participant + signed-QR ticket + Draft invoice), and a checkpoint.

No implementation code is changed — this is purely a runtime seed.
"""
import sys
from datetime import date, datetime, timezone

from app.database import SessionLocal
from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.models.tenant import Tenant

# Register every module's boot hooks (capabilities + status entities + derived
# triggers) — these normally fire at app startup. Without them, the finance
# create_invoice capability isn't registered and confirm() 409s.
from app.module_loader import discover_manifests, register_module_boot

from modules.ems.bootstrap import (
    TICKET_EDGE_SEED,
    TICKET_STATUS_SEED,
    _seed_unscoped_graph,
)
from modules.ems.models import TICKET_ENTITY, Ticket
from modules.ems.services import (
    CheckoutService,
    CheckpointService,
    OfferingService,
    ProfileService,
    ProjectService,
    ProjectTemplateService,
    ProjectTypeService,
    _status_id_by_key,
)
from app.services.catalog_service import ProductService
from app.models.catalog import Product


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _boot_modules() -> None:
    for manifest in discover_manifests():
        try:
            register_module_boot(manifest["module_name"])
        except Exception as exc:  # noqa: BLE001 — best-effort; report and continue
            print(f"  ! boot hook for {manifest['module_name']} failed: {exc}")


def _default_tenant(db) -> Tenant:
    t = (
        db.query(Tenant)
        .filter(Tenant.slug == "default", Tenant.is_platform.is_(False))
        .first()
    )
    if t is None:
        sys.exit("FATAL: default tenant not found — seed the DB first.")
    return t


# ── Problem 1 ────────────────────────────────────────────────────────────────
def reseed_ticket_graph(db, tenant_id: str) -> str | None:
    """Delete existing ticket Status rows (+edges) for the tenant fork AND the
    platform NULL-tier, repoint any live tickets at the new `issued`, then seed
    the canonical graph. Returns the resolved `issued` status id (or None)."""
    # Collect every ticket-entity status id that could resolve for this tenant:
    # the tenant fork (tenant_id matches) AND the platform NULL-tier rows.
    rows = (
        db.query(Status)
        .filter(
            Status.entity_type == TICKET_ENTITY,
            (Status.tenant_id == tenant_id) | (Status.tenant_id.is_(None)),
        )
        .all()
    )
    ids = [r.id for r in rows]
    print(f"  found {len(ids)} existing ticket Status rows to remove "
          f"(keys: {sorted({r.key for r in rows})})")

    # FK safety: if any tickets reference these ids, park them — we'll repoint to
    # the new issued id after reseed. (Fresh scenario = usually none.)
    referencing = (
        db.query(Ticket)
        .filter(Ticket.tenant_id == tenant_id, Ticket.status_id.in_(ids))
        .all()
        if ids
        else []
    )
    if referencing:
        print(f"  {len(referencing)} tickets reference the old graph — will repoint to new issued")

    if ids:
        db.query(StatusTransition).filter(
            (StatusTransition.from_status_id.in_(ids))
            | (StatusTransition.to_status_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.id.in_(ids)).delete(synchronize_session=False)
        db.flush()

    # Canonical reseed (tenant-tier, scope NULL) — now no-op-guard passes (empty).
    _seed_unscoped_graph(
        db, TICKET_ENTITY, tenant_id, TICKET_STATUS_SEED, TICKET_EDGE_SEED
    )
    db.flush()

    issued_id = _status_id_by_key(db, TICKET_ENTITY, tenant_id, "issued")
    if referencing and issued_id:
        for t in referencing:
            t.status_id = issued_id
            t.status = "issued"

    db.commit()
    return _status_id_by_key(db, TICKET_ENTITY, tenant_id, "issued")


# ── Problem 2 ────────────────────────────────────────────────────────────────
def _ensure_product(db, tenant_id: str) -> str:
    """Reuse an existing admission/GA-ish product if present, else create one."""
    svc = ProductService(db)
    existing = (
        db.query(Product)
        .filter_by(tenant_id=tenant_id, is_deleted=False)
        .first()
    )
    if existing is not None:
        print(f"  reusing core product {existing.id} ({existing.name!r}, kind={existing.kind})")
        return existing.id
    # `admission` kind is registered by EMS; falls back to `good` if filtered.
    try:
        p = svc.create(
            tenant_id,
            {"name": "GA Admission", "kind": "admission", "defaultPrice": 50, "isActive": True},
        )
    except Exception:
        p = svc.create(
            tenant_id,
            {"name": "GA Admission", "kind": "good", "defaultPrice": 50, "isActive": True},
        )
    print(f"  created core product {p.id} ({p.name!r}, kind={p.kind})")
    return p.id


def _ensure_template(db, tenant_id: str) -> str:
    """Need a project type + template (template materializes the eligibility graph)."""
    tag = _now_tag()
    ptype = ProjectTypeService(db).create(tenant_id, {"name": f"Slice3 Type {tag}"})
    tmpl = ProjectTemplateService(db).create(
        tenant_id, {"typeId": ptype.id, "name": f"Slice3 Template {tag}"}
    )
    print(f"  created project type {ptype.id} + template {tmpl.id}")
    return tmpl.id


def seed_scenario(db, tenant_id: str) -> dict:
    tag = _now_tag()
    product_id = _ensure_product(db, tenant_id)
    template_id = _ensure_template(db, tenant_id)

    # 1) fresh event
    event = ProjectService(db).create(
        tenant_id, {"templateId": template_id, "title": f"Slice3 Test Event {tag}"}
    )
    print(f"  created event {event.id} ({event.title!r})")

    # 2) published GA offering (window open now; no segment gating → any ticket admits)
    offering = OfferingService(db).create(
        tenant_id,
        event.id,
        {
            "productId": product_id,
            "price": 50,
            "currency": "SGD",
            "taxRate": 0,
            "capacity": 100,
            "allocationMode": "GA",
            "validFrom": date.today().isoformat(),
            "validUntil": date(date.today().year + 1, 12, 31).isoformat(),
        },
    )
    print(f"  created GA offering {offering.id} (capacity 100, no segment gating)")

    # 3) two profiles
    src = ProfileService(db).create(
        tenant_id,
        {"email": f"slice3-source-{tag}@example.com", "fullName": "Transfer Source"},
    )
    tgt = ProfileService(db).create(
        tenant_id,
        {"email": f"slice3-target-{tag}@example.com", "fullName": "Transfer Target"},
    )
    print(f"  created profiles source={src.id} target={tgt.id}")

    # 4) confirmed PAID ticket for the source profile (admin add-one path) —
    #    mints participant + signed-QR ticket (status issued) + Draft invoice.
    result = CheckoutService(db).confirm(
        tenant_id,
        event.id,
        [
            {
                "offeringId": offering.id,
                "attendee": {
                    "email": src.email,
                    "name": src.full_name,
                },
            }
        ],
        comp=False,
    )
    print(f"  confirm result: {result}")

    # fetch the minted ticket (the one for the source profile on this offering)
    ticket = (
        db.query(Ticket)
        .filter(
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == event.id,
            Ticket.project_product_id == offering.id,
            Ticket.attendee_profile_id == src.id,
        )
        .order_by(Ticket.created_at.desc())
        .first()
    )
    if ticket is None or not ticket.qr_token:
        sys.exit("FATAL: ticket not minted or qr_token is null — confirm path failed.")
    print(f"  minted ticket {ticket.id} status={ticket.status} qr_token set: {bool(ticket.qr_token)}")

    # 5) checkpoint (single-entry, no segment gating → admits the seeded ticket)
    checkpoint = CheckpointService(db).create(
        tenant_id, event.id, {"name": f"Main Gate {tag}", "entryType": "single"}
    )
    print(f"  created checkpoint {checkpoint.id}")

    return {
        "event_id": event.id,
        "offering_id": offering.id,
        "source_profile_id": src.id,
        "target_profile_id": tgt.id,
        "participant_id": ticket.participant_id,
        "ticket_id": ticket.id,
        "qr_token": ticket.qr_token,
        "checkpoint_id": checkpoint.id,
        "invoice_id": result.get("invoiceId"),
    }


def main() -> None:
    print("Booting module registrations (capabilities / status entities / derived triggers)…")
    _boot_modules()

    db = SessionLocal()
    try:
        tenant = _default_tenant(db)
        print(f"\nDefault tenant: {tenant.id} (slug={tenant.slug})\n")

        print("== Problem 1: reseed canonical ticket status graph ==")
        issued = reseed_ticket_graph(db, tenant.id)
        print(f"  issued status id resolves: {'YES → ' + issued if issued else 'NO'}\n")
        if not issued:
            sys.exit("FATAL: reseed failed — issued key did not resolve.")

        print("== Problem 2: seed slice-3 scenario ==")
        ids = seed_scenario(db, tenant.id)

        print("\n================ RESULT ================")
        print(f"tenant_id         = {tenant.id}")
        print(f"issued_status_id  = {issued}")
        for k, v in ids.items():
            print(f"{k:18s}= {v}")
        print("========================================")
    finally:
        db.close()


if __name__ == "__main__":
    main()

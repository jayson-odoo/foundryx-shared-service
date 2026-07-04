"""EMS importer configs (sprint-3/11; trimmed sprint-4/08) — ``profile`` (admin
bulk profile load) + ``project_participant`` (project-scoped bulk registration
with a find-or-create-by-email profile column). Client/lead importers moved to
CRM; product importer to core.

Sprint-4/05 (R3-5) adds a job-level **Ticket mode** to the project-scoped
participant importer (``participants_only`` | ``comp`` | ``paid``), carried in
``context_json`` (the seam already flows end-to-end — no schema change). Comp/Paid
require a **GA** offering; Paid requires a bill-to Client. Capacity is validated
at Test (``sold + held + import_qty <= capacity``) so a commit can never oversell;
on commit each row mints a participant + a signed-QR ticket, and Paid mints ONE
consolidated Draft invoice via ``finance.create_invoice@1`` covering all rows."""
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.import_engine.registry import (
    ImportColumn,
    ImporterDef,
    RESOLVE_FIND_OR_CREATE,
    ResolverDef,
    register_importer,
)
from app.secrets import encrypt_secret
from modules.ems.models import (
    CapacityHold,
    Profile,
    ProjectParticipant,
    ProjectProduct,
    TICKET_ENTITY,
    Ticket,
)

PROFILE_IMPORT_KEY = "profile"
PARTICIPANT_IMPORT_KEY = "project_participant"

# Ticket-mode context values (R3-5). Carried in import_jobs.context_json.
TICKET_MODE_PARTICIPANTS_ONLY = "participants_only"
TICKET_MODE_COMP = "comp"
TICKET_MODE_PAID = "paid"
TICKET_MODES = (TICKET_MODE_PARTICIPANTS_ONLY, TICKET_MODE_COMP, TICKET_MODE_PAID)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(v):
    return "not a valid email address" if v and not _EMAIL_RE.match(str(v)) else None


# ── profile importer ─────────────────────────────────────────────────────────


def _profile_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    return {
        r[0]
        for r in db.query(Profile.id)
        .filter(Profile.tenant_id == tenant_id, Profile.id.in_(ids))
        .all()
    }


def _create_profiles(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    now = datetime.now(timezone.utc)
    ids, mappings = [], []
    for r in rows:
        pid = str(uuid.uuid4())
        ids.append(pid)
        mappings.append(
            {
                "id": pid,
                "tenant_id": tenant_id,
                "email": r["email"],
                "full_name": r.get("fullName"),
                "phone": r.get("phone"),
                "country": r.get("country"),
                "organization": r.get("organization"),
                "title": r.get("title"),
                "is_deleted": False,
                "created_at": now,
                "updated_at": now,
            }
        )
    if mappings:
        db.bulk_insert_mappings(Profile, mappings)
    return ids


def _update_profiles(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    ids = []
    for r in rows:
        patch = {
            k: v
            for k, v in {
                "email": r.get("email"),
                "full_name": r.get("fullName"),
                "phone": r.get("phone"),
                "country": r.get("country"),
                "organization": r.get("organization"),
                "title": r.get("title"),
            }.items()
            if v is not None
        }
        if patch:
            db.query(Profile).filter(
                Profile.tenant_id == tenant_id, Profile.id == r["id"]
            ).update(patch, synchronize_session=False)
        ids.append(r["id"])
    return ids


# ── participant importer (project-scoped, find-or-create profile) ────────────


def _profile_by_email_lookup(db: Session, tenant_id: str, emails: List[str]) -> Dict[str, str]:
    lowered = {e.lower(): e for e in emails}
    rows = (
        db.query(Profile.email, Profile.id)
        .filter(Profile.tenant_id == tenant_id, Profile.email.in_(list(lowered.keys())))
        .all()
    )
    return {lowered[email]: pid for (email, pid) in rows if email in lowered}


def _profile_find_or_create(db: Session, tenant_id: str, row: dict, ctx: dict) -> str:
    email = str(row.get("profile") or "").strip().lower()
    pid = str(uuid.uuid4())
    db.add(
        Profile(
            id=pid,
            tenant_id=tenant_id,
            email=email,
            full_name=row.get("fullName"),
            is_deleted=False,
        )
    )
    db.flush()
    return pid


def _participant_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    return {
        r[0]
        for r in db.query(ProjectParticipant.id)
        .filter(ProjectParticipant.tenant_id == tenant_id, ProjectParticipant.id.in_(ids))
        .all()
    }


# ── ticket-mode helpers (R3-5) ───────────────────────────────────────────────


def _ticket_options(ctx: dict) -> tuple:
    """(ticket_mode, offering_id, bill_to_client_id) from the import context."""
    ctx = ctx or {}
    mode = ctx.get("ticket_mode") or TICKET_MODE_PARTICIPANTS_ONLY
    return mode, ctx.get("offering_id"), ctx.get("bill_to_client_id")


def _get_ga_offering(
    db: Session, tenant_id: str, project_id: str, offering_id: str
) -> Optional[ProjectProduct]:
    """The GA offering for THIS project, tenant-scoped. None if missing / wrong
    project / not GA — the caller decides the error (offering-required vs GA-only)."""
    return (
        db.query(ProjectProduct)
        .filter(
            ProjectProduct.id == offering_id,
            ProjectProduct.tenant_id == tenant_id,
            ProjectProduct.project_id == project_id,
        )
        .first()
    )


def _ga_remaining(db: Session, tenant_id: str, offering: ProjectProduct) -> int:
    """Live GA headroom: capacity − sold tickets (excl. void/refunded) − active
    holds. Mirrors CartService._ga_remaining (the single capacity contract)."""
    from modules.ems.services import _now

    sold = (
        db.query(Ticket)
        .filter(
            Ticket.tenant_id == tenant_id,
            Ticket.project_product_id == offering.id,
            Ticket.status.notin_(("void", "refunded")),
        )
        .count()
    )
    held_qty = (
        db.query(func.coalesce(func.sum(CapacityHold.qty), 0))
        .filter(
            CapacityHold.tenant_id == tenant_id,
            CapacityHold.project_product_id == offering.id,
            CapacityHold.expires_at > _now(),
        )
        .scalar()
    ) or 0
    return max(int(offering.capacity) - sold - int(held_qty), 0)


def _validate_participant_import(
    db: Session, tenant_id: str, rows: List[dict], ctx: dict
) -> List[dict]:
    """Aggregate Test-phase validation (AC-05-IMP-02/04). Zero writes.

    - mode≠participants_only → an offering is required, must be GA (RESERVED is
      rejected v1 — it needs interactive seat-pick);
    - mode=paid → a bill-to Client is required;
    - capacity: ``sold + held + import_qty <= capacity`` for the GA offering, else
      a single aggregate error blocks the whole commit (never oversell).
    Blocked-status profiles (AC-05-IMP-05) are handled per-row in create_rows."""
    mode, offering_id, bill_to_client_id = _ticket_options(ctx)
    if mode == TICKET_MODE_PARTICIPANTS_ONLY or mode not in TICKET_MODES:
        return []
    project_id = (ctx or {}).get("project_id")
    errors: List[dict] = []
    if not offering_id:
        return [{"row": None, "column": "ticketMode", "message": "An offering is required for Comp/Paid ticketing."}]
    offering = _get_ga_offering(db, tenant_id, project_id, offering_id)
    if offering is None:
        return [{"row": None, "column": "ticketMode", "message": "The selected offering was not found for this event."}]
    if (offering.allocation_mode or "GA") != "GA":
        return [{"row": None, "column": "ticketMode", "message": "Only GA offerings can be bulk-ticketed (RESERVED needs seat selection)."}]
    if mode == TICKET_MODE_PAID and not bill_to_client_id:
        errors.append({"row": None, "column": "ticketMode", "message": "A bill-to Client is required for Paid ticketing."})
    # capacity: one ticket per import row (admission).
    import_qty = len(rows)
    remaining = _ga_remaining(db, tenant_id, offering)
    if import_qty > remaining:
        errors.append(
            {
                "row": None,
                "column": "ticketMode",
                "message": (
                    f"Capacity exceeded: {import_qty} ticket(s) requested but only "
                    f"{remaining} remaining for this offering."
                ),
            }
        )
    return errors


def _create_participants(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    """Project from the import context (D17); profile by find-or-create-by-email
    (D18). Tier-1 gate: refuse the batch if any EXISTING profile blocks access."""
    project_id = (ctx or {}).get("project_id")
    now = datetime.now(timezone.utc)

    values = [r["profile"] for r in rows]
    matched_ids = {
        r[0]
        for r in db.query(Profile.id)
        .filter(Profile.tenant_id == tenant_id, Profile.id.in_(values))
        .all()
    }
    unmatched = {v for v in values if v not in matched_ids}
    email_to_id: Dict[str, str] = {}
    if unmatched:
        existing = {
            email.lower(): pid
            for (email, pid) in db.query(Profile.email, Profile.id)
            .filter(Profile.tenant_id == tenant_id, Profile.email.in_([e.lower() for e in unmatched]))
            .all()
        }
        new_profiles = []
        for email in unmatched:
            low = email.lower()
            if low in existing:
                email_to_id[email] = existing[low]
            else:
                pid = str(uuid.uuid4())
                email_to_id[email] = pid
                existing[low] = pid
                new_profiles.append(
                    {"id": pid, "tenant_id": tenant_id, "email": low, "is_deleted": False, "created_at": now, "updated_at": now}
                )
        if new_profiles:
            db.bulk_insert_mappings(Profile, new_profiles)

    resolved_ids = {
        (r["profile"] if r["profile"] in matched_ids else email_to_id[r["profile"]]) for r in rows
    }
    from app.models.status import Status as _Status

    blocked = (
        db.query(Profile.email)
        .join(_Status, _Status.id == Profile.status_id)
        .filter(
            Profile.tenant_id == tenant_id,
            Profile.id.in_(resolved_ids),
            _Status.blocks_access.is_(True),
        )
        .all()
    )
    if blocked:
        emails = ", ".join(sorted(e for (e,) in blocked))
        raise HTTPException(
            422,
            f"These profiles are suspended/blacklisted and can't be registered: {emails}",
        )

    mode, offering_id, bill_to_client_id = _ticket_options(ctx)
    ticketing = mode in (TICKET_MODE_COMP, TICKET_MODE_PAID)
    offering = (
        _get_ga_offering(db, tenant_id, project_id, offering_id) if ticketing else None
    )

    ids, mappings, row_links = [], [], []
    for r in rows:
        ppid = str(uuid.uuid4())
        ids.append(ppid)
        profile_id = r["profile"] if r["profile"] in matched_ids else email_to_id[r["profile"]]
        row_links.append((ppid, profile_id))
        mappings.append(
            {
                "id": ppid,
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "project_id": project_id,
                # copy the GA offering's grants onto the participant (Q3), as the
                # checkout path does — keeps bulk-ticketed registrants consistent.
                "role_id": offering.grants_role_id if offering else None,
                "segment_id": offering.grants_segment_id if offering else None,
                "is_deleted": False,
                "created_at": now,
                "updated_at": now,
            }
        )
    if mappings:
        db.bulk_insert_mappings(ProjectParticipant, mappings)

    if ticketing and offering is not None:
        _mint_tickets(
            db, tenant_id, project_id, offering, row_links, mode, bill_to_client_id
        )
    return ids


def _mint_tickets(
    db: Session,
    tenant_id: str,
    project_id: str,
    offering: ProjectProduct,
    row_links: List[tuple],
    mode: str,
    bill_to_client_id: Optional[str],
) -> None:
    """Mint one signed-QR admission ticket per row (AC-05-IMP-03). Paid → ONE
    consolidated Draft invoice to the bill-to Client covering all N lines, with
    each ticket's ``invoice_id`` set. Comp → no invoice (invoice_id NULL). Runs in
    the import's single transaction (all-or-nothing)."""
    from modules.ems.services import _initial_unscoped, _product_name

    issued = _initial_unscoped(db, TICKET_ENTITY, tenant_id)
    tickets: List[Ticket] = []
    for ppid, profile_id in row_links:
        t = Ticket(
            tenant_id=tenant_id,
            project_id=project_id,
            project_product_id=offering.id,
            attendee_profile_id=profile_id,
            participant_id=ppid,
            status="issued",
            status_id=issued,
        )
        db.add(t)
        db.flush()
        t.qr_nonce = uuid.uuid4().hex
        t.qr_token = encrypt_secret({"t": t.id, "n": t.qr_nonce})
        tickets.append(t)

    if mode != TICKET_MODE_PAID or not tickets:
        return  # comp: invoice_id stays NULL

    from app.module_platform import resolve_capability

    handler = resolve_capability(db, tenant_id, "finance.create_invoice", 1)
    if handler is None:
        raise HTTPException(409, "The Finance module is not installed for this workspace.")
    line = {
        "projectProductId": offering.id,
        "description": _product_name(db, tenant_id, offering.product_id),
        "qty": len(tickets),
        "unitPrice": offering.price or 0,
        "taxRate": offering.tax_rate or 0,
    }
    invoice = handler(
        db,
        tenant_id,
        {
            "projectId": project_id,
            "billToType": "Client",
            "billToId": bill_to_client_id,
            "lines": [line],
        },
    )
    if invoice:
        for t in tickets:
            t.invoice_id = invoice["id"]


def register_ems_importers() -> None:
    register_importer(
        ImporterDef(
            entity_type=PROFILE_IMPORT_KEY,
            label="Profile",
            model=Profile,
            columns=(
                ImportColumn(key="id", label="ID"),
                ImportColumn(
                    key="email", label="Email", required=True, unique=True,
                    transform=lambda v: str(v).strip().lower(), validators=(_valid_email,),
                ),
                ImportColumn(key="fullName", label="Full name"),
                ImportColumn(key="phone", label="Phone"),
                ImportColumn(key="country", label="Country"),
                ImportColumn(key="organization", label="Organization"),
                ImportColumn(key="title", label="Title"),
            ),
            create_rows=_create_profiles,
            update_rows=_update_profiles,
            existing_ids=_profile_existing_ids,
            module="ems",
            write_permission="profiles.manage",
        )
    )
    register_importer(
        ImporterDef(
            entity_type=PARTICIPANT_IMPORT_KEY,
            label="Participant",
            model=ProjectParticipant,
            columns=(
                ImportColumn(
                    key="profile", label="Profile email", required=True,
                    transform=lambda v: str(v).strip().lower(),
                    resolver=ResolverDef(
                        lookup=_profile_by_email_lookup,
                        mode=RESOLVE_FIND_OR_CREATE,
                        create=_profile_find_or_create,
                        label="Profile (by email)",
                    ),
                ),
                ImportColumn(key="fullName", label="Full name"),
            ),
            create_rows=_create_participants,
            existing_ids=_participant_existing_ids,
            validate_prepared=_validate_participant_import,
            # ticket_mode/offering_id/bill_to_client_id carry the R3-5 Ticket mode
            # through context_json (the existing seam — no schema change).
            context_keys=(
                "project_id",
                "ticket_mode",
                "offering_id",
                "bill_to_client_id",
            ),
            module="ems",
            write_permission="participants.manage",
        )
    )

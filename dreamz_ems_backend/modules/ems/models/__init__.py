"""EMS spine models (sprint-3/11, F4) — ``app_ems`` schema.

Identity (Profile, NOT a staff user), the Type→Template→Project hierarchy, and
the Project Participant registration join. Two-tier validity rides the status
engine: tier-1 ``Profile.status_id`` (unscoped), project lifecycle
``Project.status_id`` (unscoped), tier-2 participant eligibility (scoped, one
graph per Project). NO financial columns in F4 (Cluster F adds ticket/invoice).
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.utc_datetime import UTCDateTime
from modules.ems.db import EmsBase


def _uuid() -> str:
    return str(uuid.uuid4())


class Profile(EmsBase):
    """Participant identity — tenant-scoped, separate from staff ``users``.
    Auth columns are RESERVED (no flow in F4; the portal is Cluster D). The
    profile is the person ACROSS events; event-specific data lives in form
    submissions, not here. Dedup = lower(email), enforced at the service."""

    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_ems_profiles_tenant_email"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    email = Column(String, nullable=False)  # stored lowercased (identity key)
    phone = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    country = Column(String, nullable=True)
    organization = Column(String, nullable=True)
    title = Column(String, nullable=True)
    # RESERVED — not used in F4 (Cluster D portal auth).
    password_hash = Column(String, nullable=True)
    email_verified_at = Column(UTCDateTime, nullable=True)
    last_login_at = Column(UTCDateTime, nullable=True)
    # tier-1 (tenant-level, unscoped) status graph.
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    deleted_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class ProjectType(EmsBase):
    """Light category master data (classify/filter/report)."""

    __tablename__ = "project_types"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class ProjectTemplate(EmsBase):
    """Reusable preset (MANY per type) — owns the configurable defaults:
    eligibility flow (a scoped graph at scope_id=template_id) + roles + segments."""

    __tablename__ = "project_templates"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    type_id = Column(String, ForeignKey("project_types.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class ProjectTemplateRole(EmsBase):
    __tablename__ = "project_template_roles"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    template_id = Column(String, ForeignKey("project_templates.id"), nullable=False)
    name = Column(String, nullable=False)
    sort = Column(String, nullable=True)


class ProjectTemplateSegment(EmsBase):
    __tablename__ = "project_template_segments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    template_id = Column(String, ForeignKey("project_templates.id"), nullable=False)
    name = Column(String, nullable=False)
    sort = Column(String, nullable=True)


class Project(EmsBase):
    """An event instance, created FROM a template. UI label = "Event" via
    Terminology; canonical name stays ``project`` (admin face). ``client_id`` /
    ``domain_name`` are reserved seams (Cluster B / F5)."""

    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    template_id = Column(String, ForeignKey("project_templates.id"), nullable=False)
    type_id = Column(String, ForeignKey("project_types.id"), nullable=True)  # denorm
    title = Column(String, nullable=False)
    brief = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    client_id = Column(String, nullable=True, index=True)  # Cluster B (set on lead Won)
    lead_id = Column(String, nullable=True, index=True)  # Cluster B (set on lead Won)
    domain_name = Column(String, nullable=True)  # F5 placeholder
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    event_validity_end = Column(Date, nullable=True)
    # Checkout payment policy (R3-9): pay_now_required | pay_later_allowed.
    payment_policy = Column(String, nullable=False, default="pay_now_required")
    # Commercial mode + agency fee config (Cluster F slice 4, AC-07-45). SELF_RUN
    # = no give-back settlement; AGENCY drives the PRIMARY settlement. fee_type ∈
    # {PERCENT,FLAT,PER_TICKET}; fee_value is a small decimal (percent or money).
    commercial_mode = Column(String, nullable=False, default="SELF_RUN")  # SELF_RUN|AGENCY
    fee_type = Column(String, nullable=True)  # PERCENT|FLAT|PER_TICKET
    fee_value = Column(Float, nullable=True)
    # Per-project payment gateway (Cluster F slice 3, AC-07-25). NULL = fall back
    # to the tenant default payment connection (resolve_for_type). Core
    # connections FK = plain indexed col (BL-030).
    payment_connection_id = Column(String, nullable=True, index=True)
    # Project lifecycle (tenant-level, unscoped) status graph.
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class ProjectParticipant(EmsBase):
    """The registration join — one row per (profile, project) v1. role_id /
    segment_id FK the TEMPLATE's sub-tables (shared, not copied). tier-2
    eligibility = a scoped status (scope_id = project_id)."""

    __tablename__ = "project_participants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "profile_id", "project_id",
            name="uq_ems_participant_profile_project",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    role_id = Column(String, ForeignKey("project_template_roles.id"), nullable=True)
    segment_id = Column(String, ForeignKey("project_template_segments.id"), nullable=True)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


# Status entity keys (D9). Client/Lead/Quotation + the product catalog moved out
# of EMS in sprint-4/08 (CRM module + core catalog). Project keeps lead_id /
# client_id as soft-ref columns (link of record for the CRM lead→event capability).
PROFILE_ENTITY = "profile"
PROJECT_ENTITY = "project"
PARTICIPANT_ENTITY = "project_participant"


# ── Cluster D (sprint-4/05) — Venue master + Offerings + capacity ────────────
# Venue/offering have NO status lifecycle in slice 1 (terminology-only);
# capacity_unit.status is a SIMPLE enum (free|held|sold), not the status engine
# (the ticket entity adopts the engine in slice 3). All cross-schema/core refs
# (tenant_id, product_id, grants_*, status of nothing here) stay plain cols.
VENUE_ENTITY = "venue"
OFFERING_ENTITY = "offering"


class Venue(EmsBase):
    """Tenant-level reusable venue (NOT per-project, R3-8). Holds zones + a
    reusable seat map; events link via ``project_venues``."""

    __tablename__ = "venues"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    name = Column(String, nullable=False)
    address = Column(Text, nullable=True)
    capacity = Column(Integer, nullable=True)  # informational headline cap
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class VenueZone(EmsBase):
    """A section / hall / room within a venue. RESERVED offerings draw their
    ``capacity_units`` from one or more zones' seats."""

    __tablename__ = "venue_zones"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    venue_id = Column(String, ForeignKey("venues.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="section")  # section|hall|room
    sort = Column(Integer, nullable=False, default=0)


class VenueSeat(EmsBase):
    """A reusable physical seat in a zone. ``x``/``y`` are auto-grid coords
    (R3-4 — the visual designer repositions them later)."""

    __tablename__ = "venue_seats"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    venue_id = Column(String, ForeignKey("venues.id"), nullable=False, index=True)
    zone_id = Column(String, ForeignKey("venue_zones.id"), nullable=False, index=True)
    section = Column(String, nullable=True)
    row = Column(String, nullable=True)
    number = Column(String, nullable=True)
    label = Column(String, nullable=False)
    x = Column(Float, nullable=False, default=0)
    y = Column(Float, nullable=False, default=0)


class ProjectVenue(EmsBase):
    """Link of an event to a venue it uses."""

    __tablename__ = "project_venues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "venue_id", name="uq_ems_project_venue"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    venue_id = Column(String, ForeignKey("venues.id"), nullable=False, index=True)


class ProjectProduct(EmsBase):
    """Offering — a core catalog product priced + capacity-bounded for ONE event.
    ``product_id`` is a core-catalog soft-ref (BL-030). RESERVED offerings carry a
    ``venue_id`` + zones (``project_product_zones``) → capacity_units; GA is
    counter-only (no unit rows)."""

    __tablename__ = "project_products"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    product_id = Column(String, nullable=False, index=True)  # core catalog soft-ref
    price = Column(Float, nullable=True)  # override; null = product default
    currency = Column(String, nullable=False, default="SGD")
    tax_rate = Column(Float, nullable=False, default=0)  # percent (v1 pricing)
    capacity = Column(Integer, nullable=False, default=0)
    allocation_mode = Column(String, nullable=False, default="GA")  # GA|RESERVED
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    grants_segment_id = Column(String, nullable=True)  # → template segment (intra, soft)
    grants_role_id = Column(String, nullable=True)  # → template role (intra, soft)
    max_tickets_per_attendee = Column(Integer, nullable=True)  # R3-7 (null = unlimited)
    venue_id = Column(String, ForeignKey("venues.id"), nullable=True, index=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class ProjectProductZone(EmsBase):
    """Which venue zones a RESERVED offering draws its seats from."""

    __tablename__ = "project_product_zones"
    __table_args__ = (
        UniqueConstraint(
            "project_product_id", "zone_id", name="uq_ems_offering_zone"
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_product_id = Column(
        String, ForeignKey("project_products.id"), nullable=False, index=True
    )
    zone_id = Column(String, ForeignKey("venue_zones.id"), nullable=False, index=True)


class CapacityUnit(EmsBase):
    """A minted addressable seat for a RESERVED offering (1 unit = 1 ticket).
    ``status`` is a simple enum; ``held_*``/``participant_id`` are reserved for
    the cart-hold + ticket occupancy that land in slices 2/3."""

    __tablename__ = "capacity_units"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_product_id = Column(
        String, ForeignKey("project_products.id"), nullable=False, index=True
    )
    venue_seat_id = Column(String, ForeignKey("venue_seats.id"), nullable=True)
    label = Column(String, nullable=False)
    section = Column(String, nullable=True)
    row = Column(String, nullable=True)
    number = Column(String, nullable=True)
    zone = Column(String, nullable=True)
    x = Column(Float, nullable=False, default=0)
    y = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="free")  # free|held|sold
    held_until = Column(UTCDateTime, nullable=True)  # slice 2 (cart hold)
    held_by_cart_id = Column(String, nullable=True)  # slice 2
    participant_id = Column(String, nullable=True)  # slice 2/3 (occupancy)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


# ── Cluster D slice 2 (sprint-4/05) — cart / holds / tickets ─────────────────
TICKET_ENTITY = "ticket"  # status engine adopted in slice 3; v1 = simple string


class Cart(EmsBase):
    """Browse + hold container. Anonymous-capable (profile_id NULL + session_token);
    confirm spawns participants + tickets + a Draft invoice. TTL expiry releases holds."""

    __tablename__ = "carts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    profile_id = Column(String, nullable=True)  # set at confirm (find-or-create)
    session_token = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="open")  # open|converted|abandoned|expired
    expires_at = Column(UTCDateTime, nullable=True)
    bill_to_type = Column(String, nullable=True)  # Client | Profile (set at checkout)
    bill_to_id = Column(String, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


class CartItem(EmsBase):
    __tablename__ = "cart_items"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    cart_id = Column(String, ForeignKey("carts.id"), nullable=False, index=True)
    project_product_id = Column(String, ForeignKey("project_products.id"), nullable=False, index=True)
    qty = Column(Integer, nullable=False, default=1)
    capacity_unit_id = Column(String, ForeignKey("capacity_units.id"), nullable=True)  # RESERVED
    unit_price_snapshot = Column(Float, nullable=True)
    attendee_email = Column(String, nullable=True)
    attendee_name = Column(String, nullable=True)


class CapacityHold(EmsBase):
    """GA hold (no unit rows): remaining = capacity − sold − active holds."""

    __tablename__ = "capacity_holds"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_product_id = Column(String, ForeignKey("project_products.id"), nullable=False, index=True)
    cart_id = Column(String, ForeignKey("carts.id"), nullable=False, index=True)
    qty = Column(Integer, nullable=False, default=1)
    expires_at = Column(UTCDateTime, nullable=True)


class Ticket(EmsBase):
    """One owned unit of capacity. ADMISSION ticket assigning attendee_profile_id
    mints/links the participant; ADD_ON/MERCH attach to the same participant.
    ``invoice_id`` = app_finance soft-ref (NULL = comp). QR = signed token
    (app/secrets Fernet) encoding ``{t: ticket_id, n: qr_nonce}``.

    slice 3 (sprint-4/05): the ticket adopts the STATUS ENGINE (``status_id``,
    Issued→Valid→CheckedIn→Transferred→Void→Refunded — registered + seeded in the
    EMS bootstrap). The legacy ``status`` string is KEPT IN SYNC by the service for
    back-compat (slice-2 confirm sets both); reads should prefer ``status_id``.
    ``qr_nonce`` rotates on transfer/void/refund so the previously-issued QR
    ciphertext (carrying the old nonce) is rejected at scan."""

    __tablename__ = "tickets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    project_product_id = Column(String, ForeignKey("project_products.id"), nullable=False, index=True)
    capacity_unit_id = Column(String, ForeignKey("capacity_units.id"), nullable=True)
    attendee_profile_id = Column(String, nullable=True, index=True)  # app_ems Profile
    participant_id = Column(String, ForeignKey("project_participants.id"), nullable=True)
    invoice_id = Column(String, nullable=True, index=True)  # app_finance soft-ref
    serial_bib = Column(String, nullable=True)
    qr_token = Column(Text, nullable=True)
    qr_nonce = Column(String, nullable=True)  # rotated on transfer/void/refund (old QR dies)
    status = Column(String, nullable=False, default="issued")  # legacy mirror; status_id is canonical
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030) — slice 3
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


# ── Cluster D slice 3 (sprint-4/05) — event-day checkpoints (preview; full = H)
CHECKPOINT_ENTITY = "checkpoint"


class Checkpoint(EmsBase):
    """An event-day access gate (entrance, zone door, session room). Scans a
    ticket's QR; ``segment_id`` (nullable) gates by access segment. Slice 3 is
    check-in PREVIEW: ``entry_type`` is always ``single`` (a ticket is admitted at
    a given checkpoint at most once — re-scan = ``already_in``). Multi-entry
    re-entry tracking is deferred to Cluster H (full event-day orchestration);
    the wire schema rejects any non-single value so it can't be misconfigured."""

    __tablename__ = "checkpoints"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    segment_id = Column(String, nullable=True)  # → template segment (gate by access segment; null = any)
    entry_type = Column(String, nullable=False, default="single")  # single only (slice 3); multi = Cluster H
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


class CheckpointLog(EmsBase):
    """One scan record. Dedup (Q4 "double-entry blocked by checkpoint_logs"):
    a UNIQUE on (checkpoint_id, ticket_id, result). Combined with single-entry
    checkpoints (the only mode in slice 3), a ticket can be admitted at a given
    checkpoint at most once — the service resolves a prior ``admitted`` row and
    returns ``already_in`` rather than re-inserting; the UNIQUE is the backstop
    against a concurrent double-admit race (a 2nd ``admitted`` insert raises →
    caught → ``already_in``, never a 500). ``denied``/``already_in`` rows have a
    distinct ``result`` so the constraint never blocks legitimate audit logging."""

    __tablename__ = "checkpoint_logs"
    __table_args__ = (
        UniqueConstraint(
            "checkpoint_id", "ticket_id", "result",
            name="uq_ems_checkpoint_log_admit",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    checkpoint_id = Column(String, ForeignKey("checkpoints.id"), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    participant_id = Column(String, nullable=True, index=True)
    result = Column(String, nullable=False)  # admitted|denied|already_in
    reason = Column(String, nullable=True)  # denial/info detail
    scanned_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


# ── Profile Portal auth (sprint-4/06 slice 0a) ───────────────────────────────
# Single-use, expiring secrets for Profile authentication (mirrors core's
# invite_tokens machinery, but for the EMS Profile table). ONE table, two kinds:
#   SET_PASSWORD — a uuid capability emailed as a /portal/change-password link
#                  (invite / forgot-password / staff invite share this kind).
#   OTP          — a 6-digit numeric code stored HASHED (security.hash_password),
#                  the zero-activation emailed login fallback (short TTL).
# Single-use = stamp ``used_at``; issuing a new token of a kind for a profile
# invalidates prior outstanding ones of that kind (mirrors forgot-password).
PROFILE_TOKEN_SET_PASSWORD = "SET_PASSWORD"
PROFILE_TOKEN_OTP = "OTP"


class ProfileAuthToken(EmsBase):
    __tablename__ = "profile_auth_tokens"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # SET_PASSWORD | OTP
    # SET_PASSWORD: the plaintext uuid capability (indexed for redeem lookup).
    # OTP: the bcrypt hash of the 6-digit code (never the plaintext).
    token = Column(String, nullable=False, index=True)
    # SET_PASSWORD invites (sprint-4/06 slice 0b) may carry a persona+context to
    # grant on acceptance (AC-06-15a / AC-06-22 INVITE path). NULL = plain invite.
    grant_persona_key = Column(String, nullable=True)
    grant_scope_type = Column(String, nullable=True)
    grant_scope_id = Column(String, nullable=True)
    expires_at = Column(UTCDateTime, nullable=False)
    used_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)


# ── Profile Portal persona RBAC (sprint-4/06 slice 0b) ───────────────────────
# A SEPARATE role/permission system for EMS ``Profile`` actors (AC-06-19..22) —
# fully disjoint from the core staff ``permissions`` catalog (no name-collision;
# the templates.read lesson). Personas grant PORTAL-permission keys (a code-side
# catalog in ``portal_rbac.py``, never synced into core ``permissions``).
PERSONA_GRANT_AUTO = "AUTO"      # auto-derived from a domain fact (registration→participant)
PERSONA_GRANT_STAFF = "STAFF"    # explicit staff assignment
PERSONA_GRANT_INVITE = "INVITE"  # self-claim via a set-password invite link

# Scope discriminators for a persona membership (AC-06-20). A tenant-wide
# membership uses ``scope_id=NULL``; a per-event membership uses ``project``.
PERSONA_SCOPE_TENANT = "tenant"
PERSONA_SCOPE_PROJECT = "project"


class Persona(EmsBase):
    """A tenant-configurable Profile role (AC-06-19). System personas
    (``is_system``) are delete-locked — key + flags locked, label editable;
    tenants may add custom personas. UNIQUE(tenant_id, key)."""

    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_ems_persona_tenant_key"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    key = Column(String, nullable=False)  # stable identity (locked on system rows)
    label = Column(String, nullable=False)  # display (editable on system rows)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class PersonaPermission(EmsBase):
    """A portal-permission key granted to a persona (AC-06-21). The key is a
    member of the SEPARATE portal-permission catalog (``portal_rbac.py``) —
    NEVER the core ``permissions`` table. UNIQUE(persona_id, permission_key)."""

    __tablename__ = "persona_permissions"
    __table_args__ = (
        UniqueConstraint(
            "persona_id", "permission_key", name="uq_ems_persona_permission"
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    persona_id = Column(String, ForeignKey("personas.id"), nullable=False, index=True)
    permission_key = Column(String, nullable=False)


class PersonaMembership(EmsBase):
    """A Profile's persona membership in a scope (AC-06-20). A Profile can hold
    DIFFERENT personas in different scopes (reviewer on project X, participant on
    project Y). UNIQUE(profile_id, persona_id, scope_type, scope_id). A NULL
    ``scope_id`` is a tenant-wide membership; ``granted_via`` records the
    acquisition path (AUTO|STAFF|INVITE, AC-06-22)."""

    __tablename__ = "persona_memberships"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "persona_id",
            "scope_type",
            "scope_id",
            name="uq_ems_persona_membership",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False, index=True)
    persona_id = Column(String, ForeignKey("personas.id"), nullable=False, index=True)
    scope_type = Column(String, nullable=False, default=PERSONA_SCOPE_TENANT)
    scope_id = Column(String, nullable=True, index=True)  # NULL = tenant-wide
    granted_via = Column(String, nullable=False, default=PERSONA_GRANT_STAFF)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)

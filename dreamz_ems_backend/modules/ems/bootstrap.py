"""EMS module bootstrap — the App-Store contract + engine registrations (D9).

Since sprint-4/08 EMS is events-only: leads/clients/quotations moved to the CRM
module, the product catalog to core. EMS now PROVIDES the lead→event seam:
``project.create_from_template`` + ``projects.by_lead`` / ``projects.by_client``
(consumed by CRM), and registers its domain product kinds into the core catalog
kind registry.
"""
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.rule_engine.aggregates import AggregatableRelation
from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv
from modules.ems.db import EMS_SCHEMA, EmsBase
from modules.ems.models import (
    PARTICIPANT_ENTITY,
    PROFILE_ENTITY,
    PROJECT_ENTITY,
    TICKET_ENTITY,
    Profile,
    Project,
    ProjectParticipant,
    ProjectTemplate,
    Ticket,
)

MODULE_NAME = "ems"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


# ── status seeds (tenant-level, unscoped) ───────────────────────────────────

# (key, label, color, sort, flags)
PROFILE_STATUS_SEED = [
    ("active", "Active", "green", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("suspended", "Suspended", "amber", 2, {"blocks_access": True}),
    ("blacklisted", "Blacklisted", "red", 3, {"blocks_access": True}),
]
PROFILE_EDGE_SEED = [
    ("active", "suspended", "Suspend", 1),
    ("suspended", "active", "Reactivate", 2),
    ("active", "blacklisted", "Blacklist", 3),
    ("suspended", "blacklisted", "Blacklist", 4),
    ("blacklisted", "active", "Restore", 5),
]
PROJECT_STATUS_SEED = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("planning", "Planning", "blue", 2, {"is_active": True}),
    ("active", "Active", "green", 3, {"is_active": True}),
    ("completed", "Completed", "teal", 4, {"is_terminal": True}),
    ("cancelled", "Cancelled", "red", 5, {"is_terminal": True}),
]
PROJECT_EDGE_SEED = [
    ("draft", "planning", "Start planning", 1),
    ("planning", "active", "Activate", 2),
    ("active", "completed", "Complete", 3),
    ("draft", "cancelled", "Cancel", 4),
    ("planning", "cancelled", "Cancel", 5),
    ("active", "cancelled", "Cancel", 6),
]
# Participant tier-2 eligibility — the TEMPLATE's default graph (copied per
# project at creation via copy_scope). Materialized at template creation.
PARTICIPANT_SCOPE_SEED_STATUSES = [
    ("registered", "Registered", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("pending_payment", "Pending Payment", "amber", 2, {"is_active": True}),
    ("eligible", "Eligible", "green", 3, {}),
    ("checked_in", "Checked-in", "teal", 4, {}),
    ("cancelled", "Cancelled", "red", 5, {"is_terminal": True}),
]

# Derived check-in condition (sprint-4/03 R3-2): a participant auto-advances
# Eligible→Checked-in once ALL their admission tickets are checked in (and they
# hold at least one). Cross-fact eq + a `>0` guard (both-zero never fires).
# checkedInTicketCount / admissionTicketCount are aggregate facts registered on
# the record:project_participant source below.
PARTICIPANT_CHECKIN_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {
            "kind": "condition",
            "fact": "record.admissionTicketCount",
            "operator": "gt",
            "valueKind": "literal",
            "value": 0,
        },
        {
            "kind": "condition",
            "fact": "record.checkedInTicketCount",
            "operator": "eq",
            "valueKind": "fact",
            "value": "record.admissionTicketCount",
        },
    ],
}

# Eligibility DROP on refund (Cluster F slice 4, AC-07-44): an Eligible
# participant whose last live admission ticket is refunded drops back to
# Pending Payment (no live admission ticket left). The refund→ticket→participant
# re-derive fires this AUTO edge.
PARTICIPANT_DROP_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {
            "kind": "condition",
            "fact": "record.admissionTicketCount",
            "operator": "eq",
            "valueKind": "literal",
            "value": 0,
        },
    ],
}

# Edges are 4-tuples (manual) or 6-tuples (fk, tk, label, sort, trigger_mode,
# conditions) — the Eligible→Checked-in edge is the derived AUTO consumer.
PARTICIPANT_SCOPE_SEED_EDGES = [
    ("registered", "pending_payment", "Await payment", 1),
    ("pending_payment", "eligible", "Mark eligible", 2),
    ("registered", "eligible", "Mark eligible", 3),
    ("eligible", "checked_in", "Check in", 4, "auto", PARTICIPANT_CHECKIN_CONDITIONS),
    ("registered", "cancelled", "Cancel", 5),
    ("pending_payment", "cancelled", "Cancel", 6),
    # AC-07-44 — Eligible drops to Pending Payment when no live admission ticket
    # remains (its only paid ticket was refunded). AUTO, re-derived off the
    # refunded ticket via the ticket→participant DerivedTrigger.
    ("eligible", "pending_payment", "Drop eligibility", 7, "auto", PARTICIPANT_DROP_CONDITIONS),
]

# ── ticket status entity (slice 3) — unscoped, tenant-tier ───────────────────
TICKET_STATUS_SEED = [
    ("issued", "Issued", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("valid", "Valid", "green", 2, {"is_active": True}),
    ("checked_in", "Checked-in", "teal", 3, {"is_active": True}),
    ("transferred", "Transferred", "blue", 4, {"is_terminal": True}),
    ("void", "Void", "red", 5, {"is_terminal": True}),
    ("refunded", "Refunded", "amber", 6, {"is_terminal": True}),
]
TICKET_EDGE_SEED = [
    ("issued", "valid", "Validate", 1),
    ("valid", "checked_in", "Check in", 2),
    ("issued", "checked_in", "Check in", 3),  # gate can admit a still-Issued ticket
    ("valid", "transferred", "Transfer", 4),
    ("issued", "transferred", "Transfer", 5),
    ("valid", "void", "Void", 6),
    ("issued", "void", "Void", 7),
    ("checked_in", "void", "Void", 8),
    ("valid", "refunded", "Refund", 9),
    ("issued", "refunded", "Refund", 10),
]

# Domain product kinds registered INTO the core catalog kind registry (metadata
# only — core never branches on kind). Hidden when EMS is uninstalled.
EMS_PRODUCT_KINDS = [
    ("admission", "Admission", 10),
    ("add_on", "Add-on", 11),
    ("merchandise", "Merchandise", 12),
]


def create_schema_and_tables(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{EMS_SCHEMA}"'))
    EmsBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def _seed_unscoped_graph(db, entity_type, tenant_id, statuses, edges) -> None:
    """Seed a tenant-level (scope_id NULL) status graph if absent."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    existing = (
        db.query(Status.id)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id.is_(None),
        )
        .first()
    )
    if existing is not None:
        return
    by_key = {}
    for key, label, color, sort, flags in statuses:
        row = Status(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            key=key,
            category=key.upper(),
            label=label,
            color=color,
            sort_order=sort,
            is_system=False,
            tenant_id=tenant_id,
            **{f: bool(v) for f, v in flags.items()},
        )
        db.add(row)
        by_key[key] = row
    db.flush()
    for fk, tk, label, sort in edges:
        db.add(
            StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=entity_type,
                tenant_id=tenant_id,
                from_status_id=by_key[fk].id,
                to_status_id=by_key[tk].id,
                label=label,
                sort_order=sort,
            )
        )
    db.flush()


# ── persona RBAC seeds (sprint-4/06 0b) ──────────────────────────────────────
# System personas (delete-locked) + their default portal-key grants. The grant
# keys align with the portal SURFACES registered in register_engine_entities
# (participant→My Submissions + Submit, reviewer→My Reviews, decision_maker→
# Decisions). AC-06-49 (full EMS review config seed) is slice 1; here = personas
# + grants + surfaces only.
SYSTEM_PERSONA_SEED = [
    # (key, label, sort, [portal permission keys])
    ("participant", "Participant", 1, ["my_submissions.read", "forms.submit"]),
    ("reviewer", "Reviewer", 2, ["my_reviews.read"]),
    ("decision_maker", "Decision Maker", 3, ["decisions.read"]),
]


def _seed_personas(db: Session, tenant_id: str) -> None:
    """Idempotent seed of the system personas + their portal-key grants."""
    from modules.ems.models import Persona, PersonaPermission

    for key, label, sort, perm_keys in SYSTEM_PERSONA_SEED:
        persona = (
            db.query(Persona)
            .filter(Persona.tenant_id == tenant_id, Persona.key == key)
            .first()
        )
        if persona is None:
            persona = Persona(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                key=key,
                label=label,
                is_system=True,
                sort_order=sort,
            )
            db.add(persona)
            db.flush()
        # Seed the default grants only if the persona has none yet (operator
        # edits survive reseed — mirrors the template-engine reseed contract).
        has_grants = (
            db.query(PersonaPermission.id)
            .filter(PersonaPermission.persona_id == persona.id)
            .first()
            is not None
        )
        if not has_grants:
            for pk in perm_keys:
                db.add(
                    PersonaPermission(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        persona_id=persona.id,
                        permission_key=pk,
                    )
                )
    db.flush()


def install_tenant(db: Session, tenant_id: str) -> None:
    _seed_unscoped_graph(db, PROFILE_ENTITY, tenant_id, PROFILE_STATUS_SEED, PROFILE_EDGE_SEED)
    _seed_unscoped_graph(db, PROJECT_ENTITY, tenant_id, PROJECT_STATUS_SEED, PROJECT_EDGE_SEED)
    _seed_unscoped_graph(db, TICKET_ENTITY, tenant_id, TICKET_STATUS_SEED, TICKET_EDGE_SEED)
    _seed_personas(db, tenant_id)


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    # Self-heal in-place upgrades. A tenant that installed EMS before Cluster D
    # slice 3 has no ticket status graph → `_status_id_by_key(TICKET_ENTITY, …)`
    # returns None → 409 "ticket status graph is not seeded" on the first
    # scan/nominate. `_seed_unscoped_graph` is idempotent (no-op when present),
    # so this is safe to run on every update. The caller commits.
    _seed_unscoped_graph(db, TICKET_ENTITY, tenant_id, TICKET_STATUS_SEED, TICKET_EDGE_SEED)
    # Self-heal the persona RBAC seed for tenants that installed EMS before
    # Cluster E (sprint-4/06 0b). Idempotent.
    _seed_personas(db, tenant_id)
    # AC-07-44 backfill (Cluster F slice 4): add the Eligible→Pending Payment
    # drop AUTO edge to EXISTING per-template + per-project scoped participant
    # graphs (a new graph gets it from the seed; seed-if-absent does NOT repair
    # an existing scoped graph — AC-07-53).
    _backfill_participant_drop_edge(db, tenant_id)


def _backfill_participant_drop_edge(db: Session, tenant_id: str) -> int:
    """Add the Eligible→Pending Payment AUTO edge to every existing SCOPED
    participant graph that lacks it (AC-07-44). Idempotent. Returns rows added."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    rows = (
        db.query(Status)
        .filter(
            Status.entity_type == PARTICIPANT_ENTITY,
            Status.tenant_id == tenant_id,
            Status.scope_id.isnot(None),
        )
        .all()
    )
    by_scope: dict = {}
    for r in rows:
        by_scope.setdefault(r.scope_id, {})[r.key] = r
    added = 0
    for scope_id, by_key in by_scope.items():
        eligible = by_key.get("eligible")
        pending = by_key.get("pending_payment")
        if eligible is None or pending is None:
            continue  # operator renamed a key away — don't synthesize
        exists = (
            db.query(StatusTransition.id)
            .filter(
                StatusTransition.entity_type == PARTICIPANT_ENTITY,
                StatusTransition.tenant_id == tenant_id,
                StatusTransition.from_status_id == eligible.id,
                StatusTransition.to_status_id == pending.id,
            )
            .first()
        )
        if exists is not None:
            continue
        db.add(
            StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=PARTICIPANT_ENTITY,
                tenant_id=tenant_id,
                from_status_id=eligible.id,
                to_status_id=pending.id,
                label="Drop eligibility",
                sort_order=7,
                trigger_mode="auto",
                conditions_json=PARTICIPANT_DROP_CONDITIONS,
            )
        )
        added += 1
    db.flush()
    return added


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    for table in reversed(EmsBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    ids = [
        r[0]
        for r in db.query(Status.id)
        .filter(
            Status.tenant_id == tenant_id,
            Status.entity_type.in_(
                [PROFILE_ENTITY, PROJECT_ENTITY, PARTICIPANT_ENTITY, TICKET_ENTITY]
            ),
        )
        .all()
    ]
    if ids:
        db.query(StatusTransition).filter(
            (StatusTransition.from_status_id.in_(ids))
            | (StatusTransition.to_status_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.id.in_(ids)).delete(synchronize_session=False)


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return (
        db.query(Profile.id).filter(Profile.tenant_id == tenant_id).first() is not None
    )


# ── engine registrations (boot) ─────────────────────────────────────────────


def register_engine_entities() -> None:
    """Status entities + terminology + importers + workflow entities + product
    kinds (D9). Idempotent — safe to call at every boot/bootstrap.
    The project←participant DerivedTrigger is auto-generated from the project
    entity's aggregatable_relations (sprint-4/03 Slice 4) — no hand wiring here;
    the participant→project re-derive relies on ParticipantService.add emitting
    the participant entity event."""
    _register_status_entities()
    _register_terminology()
    _register_importers()
    _register_product_kinds()
    _register_portal_surfaces()
    _register_review_resolvers()
    # Post-payment reaction (Cluster F slice 3, AC-07-35): invoice→Paid makes
    # tickets Valid + participants Eligible + enqueues a receipt. Subscribes the
    # failure-isolated event bus.
    from modules.ems.post_payment import register_post_payment_reaction

    register_post_payment_reaction()


def _count_by_status(model):
    def counter(db, status_id, tenant_id):
        q = db.query(model).filter(model.status_id == status_id)
        if tenant_id is not None:
            q = q.filter(model.tenant_id == tenant_id)
        return q.count()

    return counter


def _migrate_by_status(model):
    def migrator(db, from_id, to_id, tenant_id):
        q = db.query(model).filter(model.status_id == from_id)
        if tenant_id is not None:
            q = q.filter(model.tenant_id == tenant_id)
        n = q.update({model.status_id: to_id}, synchronize_session=False)
        db.flush()
        return n

    return migrator


def _participant_scope_exists(db, tenant_id, scope_id):
    """The participant eligibility graph has TWO valid scope owners: a template
    (graph materialized at template creation) and a project (graph copied at
    project creation). Both must pass the scope guard."""
    if (
        db.query(Project.id)
        .filter(Project.id == scope_id, Project.tenant_id == tenant_id)
        .first()
        is not None
    ):
        return True
    return (
        db.query(ProjectTemplate.id)
        .filter(ProjectTemplate.id == scope_id, ProjectTemplate.tenant_id == tenant_id)
        .first()
        is not None
    )


def _register_status_entities() -> None:
    from app.status_engine.registry import StatusEntity, register_status_entity

    register_status_entity(
        StatusEntity(
            entity_type=PROFILE_ENTITY,
            label="Profile",
            module=MODULE_NAME,
            count_records=_count_by_status(Profile),
            migrate_records=_migrate_by_status(Profile),
            record_label_attr="full_name",
            required_flags=["is_initial", "blocks_access"],
            model=Profile,
            fact_attrs=[
                "email",
                "full_name",
                "phone",
                "country",
                "organization",
                "title",
            ],
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=PROJECT_ENTITY,
            label="Event",
            module=MODULE_NAME,
            count_records=_count_by_status(Project),
            migrate_records=_migrate_by_status(Project),
            record_label_attr="title",
            required_flags=["is_initial", "is_terminal"],
            model=Project,
            fact_attrs=[
                "title",
                "brief",
                "notes",
                "domain_name",
                # Date facts (UTCDateTime → type "date", before/after/between
                # operators). NOTE: these compare to a FIXED date — for a
                # "passed now" time-based auto edge, add a computed boolean fact
                # (the rule engine has no 'now' literal) + has_time_auto_edges.
                "start_date",
                "end_date",
                "event_validity_end",
            ],
            # Time-dependent date conditions ride the auto-generated day-count
            # facts (sprint-4/03 Slice 6): "Days since End Date" etc. (no hand
            # boolean) — e.g. close 2 days after end = `Days since End Date ≥ 2`.
            # Declarative aggregate whitelist (sprint-4/03 Slice 4): the
            # participants relation auto-generates "Participants · Count"
            # (record.participants.count) + the participant→project re-derive
            # trigger. Authored in the RuleBuilder for an auto edge (e.g.
            # Draft→Confirmed when participant count >= N).
            aggregatable_relations=[
                AggregatableRelation(
                    key="participants",
                    label="Participants",
                    child_entity_type=PARTICIPANT_ENTITY,
                    child_model=ProjectParticipant,
                    fk_attr="project_id",
                    count=True,
                ),
            ],
            # Time sweep (sprint-4/03 Slice 3): event-driven re-eval can't catch
            # the clock merely advancing past end_date with no write, so the 60s
            # beat (`reevaluate_time_based`) re-checks these candidates. Coarse —
            # any non-deleted project with an end_date; reevaluate fail-closes the rest.
            has_time_auto_edges=True,
            time_candidates=lambda db: db.query(Project)
            .filter(
                Project.is_deleted.is_(False),
                or_(
                    Project.start_date.isnot(None),
                    Project.end_date.isnot(None),
                    Project.event_validity_end.isnot(None),
                ),
            )
            .all(),
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=TICKET_ENTITY,
            label="Ticket",
            module=MODULE_NAME,
            count_records=_count_by_status(Ticket),
            migrate_records=_migrate_by_status(Ticket),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            model=Ticket,
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=PARTICIPANT_ENTITY,
            label="Participant",
            module=MODULE_NAME,
            count_records=_count_by_status(ProjectParticipant),
            migrate_records=_migrate_by_status(ProjectParticipant),
            scoped=True,
            scope_attr="project_id",
            scope_label="Event",
            scope_exists=_participant_scope_exists,
            record_label_attr="id",
            required_flags=["is_initial", "is_active"],
            model=ProjectParticipant,
            # Derived check-in (sprint-4/03 R3-2): the auto-edge condition reads
            # these filtered aggregate facts. AggregatableRelation's plain count
            # can't filter by status/kind, so register raw aggregate_facts with
            # an explicit `where=`. Both are owner- AND tenant-scoped by contract.
            aggregate_facts=_participant_ticket_facts(),
        )
    )
    # Cross-entity re-derive (sprint-4/03 R3-2): a ticket change re-evaluates the
    # owning participant. Idempotent. The ticket check-in write path MUST emit the
    # ticket entity event (notify_entity_event) or this never fires (documented
    # contract — wired in TicketService.scan/transition).
    _register_checkin_derived_trigger()


def _participant_ticket_facts():
    """Aggregate facts on record:project_participant for the derived check-in
    (sprint-4/03 R3-2). Filtered counts → raw aggregate_fact(where=) (the
    declarative AggregatableRelation count can't filter). Tenant- + owner-scoped
    by aggregate_fact's resolver.

    - admissionTicketCount: the participant's LIVE admission tickets (everything
      except void/refunded/transferred — those no longer admit). v1 mints one
      admission ticket per attendee, so this is the denominator.
    - checkedInTicketCount: of those, the ones at the CheckedIn ticket status.

    Both filter the legacy ``Ticket.status`` string mirror (kept in sync with
    ``status_id`` by TicketService) — a status-string filter is portable across
    tenants without resolving per-tenant status ids inside the aggregate clause.
    """
    from app.rule_engine.aggregates import aggregate_fact

    live = Ticket.status.notin_(["void", "refunded", "transferred"])
    return [
        aggregate_fact(
            "record.admissionTicketCount",
            "Admission ticket count",
            child_model=Ticket,
            fk_attr="participant_id",
            op="count",
            where=live,
        ),
        aggregate_fact(
            "record.checkedInTicketCount",
            "Checked-in ticket count",
            child_model=Ticket,
            fk_attr="participant_id",
            op="count",
            where=Ticket.status == "checked_in",
        ),
    ]


def _register_checkin_derived_trigger() -> None:
    """A ticket event re-derives the owning participant (sprint-4/03 R3-2).
    Resolve the participant from ``ticket.participant_id``, tenant-scoped."""
    from app.status_engine.derived import DerivedTrigger, register_derived_trigger

    def _owners(db, tenant_id, ev):
        ticket = (
            db.query(Ticket)
            .filter(Ticket.id == ev.get("record_id"), Ticket.tenant_id == tenant_id)
            .first()
        )
        if ticket is None or not ticket.participant_id:
            return []
        owner = (
            db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.id == ticket.participant_id,
                ProjectParticipant.tenant_id == tenant_id,
            )
            .first()
        )
        return [owner] if owner is not None else []

    register_derived_trigger(
        DerivedTrigger(
            owner_entity=PARTICIPANT_ENTITY,
            trigger_entity=TICKET_ENTITY,
            resolve_owners=_owners,
        )
    )


def _register_review_resolvers() -> None:
    """Register EMS's PERSONA actor-pool resolver + the ``profile`` contact
    resolver into the CORE review engine (keeps core EMS-free, AC-06-49/50/51).

    - PERSONA pool = Profiles holding the role's ``bound_persona_id`` (via a
      persona membership), tenant-scoped, EXCLUDING profiles whose tier-1 status
      ``blocks_access`` (AC-06-51, the staff boundary already does this for
      participation). When the submission belongs to a project scope, project +
      tenant-wide memberships of that persona both count; otherwise tenant-wide.
      Stable order (profile id) → returns ``[('profile', id), ...]``.
    - profile contact = (email, full_name), tenant-scoped, non-deleted.
    """
    from app.review_engine.resolvers import (
        register_actor_contact_resolver,
        register_actor_pool_resolver,
        register_context_label_resolver,
        register_surface_granter,
    )

    def _persona_pool(db, tenant_id, role, submission):
        from app.models.status import Status
        from modules.ems.models import (
            PERSONA_SCOPE_PROJECT,
            PersonaMembership,
            Profile,
        )

        persona_id = getattr(role, "bound_persona_id", None)
        if not persona_id:
            return []

        # Derive a project scope from the submission's subject when it points at a
        # project (event review). subject_id may be a project OR a participant;
        # we only narrow when it resolves to a project the tenant owns.
        project_scope_id = None
        subject_id = getattr(submission, "subject_id", None) if submission is not None else None
        if subject_id:
            if (
                db.query(Project.id)
                .filter(Project.id == subject_id, Project.tenant_id == tenant_id)
                .first()
                is not None
            ):
                project_scope_id = subject_id

        q = (
            db.query(PersonaMembership.profile_id)
            .filter(
                PersonaMembership.tenant_id == tenant_id,
                PersonaMembership.persona_id == persona_id,
            )
        )
        if project_scope_id is not None:
            # tenant-wide (scope_id NULL) OR this project's scoped memberships.
            q = q.filter(
                (PersonaMembership.scope_id.is_(None))
                | (
                    (PersonaMembership.scope_type == PERSONA_SCOPE_PROJECT)
                    & (PersonaMembership.scope_id == project_scope_id)
                )
            )
        member_ids = {r[0] for r in q.all()}
        if not member_ids:
            return []

        # Tenant-scoped profiles, non-deleted, ordered by id (stable). Exclude
        # blocks_access tier-1 statuses (AC-06-51).
        blocked_status_ids = {
            r[0]
            for r in db.query(Status.id)
            .filter(Status.tenant_id == tenant_id, Status.blocks_access.is_(True))
            .all()
        }
        rows = (
            db.query(Profile.id, Profile.status_id)
            .filter(
                Profile.tenant_id == tenant_id,
                Profile.id.in_(member_ids),
                Profile.is_deleted.is_(False),
            )
            .order_by(Profile.id.asc())
            .all()
        )
        return [
            ("profile", pid)
            for pid, status_id in rows
            if status_id not in blocked_status_ids
        ]

    def _profile_contact(db, tenant_id, actor_id):
        p = (
            db.query(Profile)
            .filter(
                Profile.id == actor_id,
                Profile.tenant_id == tenant_id,
                Profile.is_deleted.is_(False),
            )
            .first()
        )
        if p is None or not p.email:
            return None
        return (p.email, p.full_name or p.email)

    def _project_context_label(db, tenant_id, context_id):
        """The event/project name for a config bound to ``context_type='project'``
        (AC-06-25) — so the review surfaces + filter pill show the real event name
        instead of an id prefix. Tenant-scoped; None for a foreign/missing id."""
        row = (
            db.query(Project.title)
            .filter(Project.id == context_id, Project.tenant_id == tenant_id)
            .first()
        )
        return row[0] if row else None

    # AC-06-22 — a PROFILE actor BOUND TO A REVIEW ROLE auto-acquires the matching
    # system persona (and thus its portal surface key), so an EXPLICIT / RULE /
    # STAFF_ROLE-sourced profile reviewer/decider/submitter can SEE their own work
    # in the portal even though they hold no persona via the domain (only
    # PERSONA-sourced roles imply a persona membership). Capability → system
    # persona key; scoped to the config context (project) when present, else
    # tenant-wide. via=AUTO + idempotent + failure-isolated (grant_persona is).
    _CAPABILITY_PERSONA = {
        "submit": "participant",
        "review": "reviewer",
        "decide": "decision_maker",
    }

    def _surface_granter(db, tenant_id, profile_id, capability, context_type, context_id):
        from modules.ems.models import (
            PERSONA_GRANT_AUTO,
            PERSONA_SCOPE_PROJECT,
            PERSONA_SCOPE_TENANT,
        )
        from modules.ems.persona_service import grant_persona

        persona_key = _CAPABILITY_PERSONA.get(capability)
        if persona_key is None:
            return
        if context_type == "project" and context_id:
            scope_type, scope_id = PERSONA_SCOPE_PROJECT, context_id
        else:
            scope_type, scope_id = PERSONA_SCOPE_TENANT, None
        # commit=False — the granter runs inside the caller's transaction
        # (allocate / config save); the caller owns the commit.
        grant_persona(
            db, tenant_id, profile_id, persona_key, scope_type, scope_id,
            PERSONA_GRANT_AUTO, commit=False,
        )

    register_actor_pool_resolver("PERSONA", _persona_pool)
    register_actor_contact_resolver("profile", _profile_contact)
    register_context_label_resolver("project", _project_context_label)
    register_surface_granter(_surface_granter)


def _register_terminology() -> None:
    from app.terminology.registry import TermDef, register_term

    for key, sing, plur in [
        (PROJECT_ENTITY, "Event", "Events"),
        ("project_type", "Event Type", "Event Types"),
        ("project_template", "Event Template", "Event Templates"),
        (PARTICIPANT_ENTITY, "Participant", "Participants"),
        (PROFILE_ENTITY, "Profile", "Profiles"),
        # Cluster D (sprint-4/05)
        ("venue", "Venue", "Venues"),
        ("offering", "Offering", "Offerings"),
        (TICKET_ENTITY, "Ticket", "Tickets"),
        ("checkpoint", "Checkpoint", "Checkpoints"),
    ]:
        register_term(TermDef(key, sing, plur, module=MODULE_NAME, group="Events"))


def _register_importers() -> None:
    from modules.ems.importers import register_ems_importers

    register_ems_importers()


def _register_portal_surfaces() -> None:
    """Register the EMS portal surfaces + their gating portal-permission keys
    (sprint-4/06 0b, AC-06-23). The surface registry seeds itself lazily; force
    it here so the catalog + surfaces are populated at boot."""
    from modules.ems.portal_rbac import ensure_seeded as ensure_portal_perms
    from modules.ems.portal_surfaces import ensure_seeded as ensure_surfaces

    ensure_surfaces()
    ensure_portal_perms()


def _register_product_kinds() -> None:
    """Register EMS domain product kinds into the CORE catalog registry (metadata
    only). Hidden when EMS is uninstalled (active_kinds filters by module)."""
    from app.catalog.kinds import ProductKind, register_product_kind

    for key, label, sort in EMS_PRODUCT_KINDS:
        register_product_kind(ProductKind(key, label, MODULE_NAME, sort))


def register_capabilities() -> None:
    """profile/participant resolve + the lead→event seam (D1). project.create_from_
    template is the CRM lead→event handler; projects.by_lead/by_client let CRM list
    a lead's/client's events. All tenant-scoped internally."""
    from app.module_platform import CapabilityDef, register_capability

    def _profile_resolve(db, tenant_id, payload):
        p = (
            db.query(Profile)
            .filter(Profile.id == payload["id"], Profile.tenant_id == tenant_id)
            .first()
        )
        return None if p is None else {"id": p.id, "email": p.email, "fullName": p.full_name}

    def _participant_resolve(db, tenant_id, payload):
        pp = (
            db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.id == payload["id"],
                ProjectParticipant.tenant_id == tenant_id,
            )
            .first()
        )
        return None if pp is None else {"id": pp.id, "projectId": pp.project_id}

    def _project_create_from_template(db, tenant_id, payload):
        from modules.ems.services import ProjectService

        p = ProjectService(db).create_for_lead(
            tenant_id,
            template_id=payload["templateId"],
            title=payload.get("title"),
            client_id=payload.get("clientId"),
            lead_id=payload.get("leadId"),
        )
        return {"id": p.id, "title": p.title, "statusId": p.status_id}

    def _projects_by_lead(db, tenant_id, payload):
        rows = (
            db.query(Project)
            .filter(
                Project.tenant_id == tenant_id,
                Project.lead_id == payload["leadId"],
                Project.is_deleted.is_(False),
            )
            .order_by(Project.created_at.desc())
            .all()
        )
        return [{"id": p.id, "title": p.title, "statusId": p.status_id} for p in rows]

    def _projects_by_client(db, tenant_id, payload):
        rows = (
            db.query(Project)
            .filter(
                Project.tenant_id == tenant_id,
                Project.client_id == payload["clientId"],
                Project.is_deleted.is_(False),
            )
            .order_by(Project.created_at.desc())
            .all()
        )
        return [{"id": p.id, "title": p.title, "statusId": p.status_id} for p in rows]

    def _project_payment_connection(db, tenant_id, payload):
        """Cluster F slice 3 (AC-07-25) — the finance checkout reads a project's
        per-project gateway override via this capability (BL-030 soft-ref, no
        cross-schema query). Tenant-scoped."""
        p = (
            db.query(Project)
            .filter(Project.id == payload["id"], Project.tenant_id == tenant_id)
            .first()
        )
        return None if p is None else {"paymentConnectionId": p.payment_connection_id}

    def _project_commercial(db, tenant_id, payload):
        """Cluster F slice 4 (AC-07-45) — settlement reads a project's commercial
        mode + agency fee config + paid-ticket count (PER_TICKET fee). Tenant-
        scoped soft-ref read (BL-030)."""
        p = (
            db.query(Project)
            .filter(Project.id == payload["id"], Project.tenant_id == tenant_id)
            .first()
        )
        if p is None:
            return None
        # Live admission tickets sold for this project (PER_TICKET fee base).
        ticket_count = (
            db.query(Ticket)
            .filter(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == p.id,
                Ticket.status.notin_(["void", "refunded", "transferred"]),
            )
            .count()
        )
        return {
            "commercialMode": p.commercial_mode,
            "feeType": p.fee_type,
            "feeValue": p.fee_value,
            "clientId": p.client_id,
            "title": p.title,
            "ticketCount": ticket_count,
        }

    def _tickets_for_invoice(db, tenant_id, payload):
        """Cluster F slice 4 (AC-07-37) — list an invoice's refundable tickets so
        finance can build per-ticket refund lines + the FE refund picker. Tenant-
        scoped (AC-07-49)."""
        rows = (
            db.query(Ticket)
            .filter(
                Ticket.tenant_id == tenant_id,
                Ticket.invoice_id == payload["invoiceId"],
            )
            .all()
        )
        out = []
        for t in rows:
            out.append({
                "id": t.id,
                "projectId": t.project_id,
                "status": t.status,
                "refundable": t.status not in ("void", "refunded", "transferred"),
            })
        return out

    def _ticket_refund(db, tenant_id, payload):
        """Cluster F slice 4 (AC-07-41/42) — refund ONE ticket: rotate the QR
        dead, release capacity, move to Refunded. Reuses TicketService.refund
        (the inverse of confirm). Tenant-scoped; commit owned by the caller's
        request. A non-refundable ticket returns ``{"ok": False}`` (the finance
        guard already filtered, this is defence-in-depth)."""
        from fastapi import HTTPException

        from modules.ems.services import TicketService

        try:
            res = TicketService(db).refund(tenant_id, payload["ticketId"], None)
        except HTTPException as exc:  # noqa: BLE001 — non-refundable / missing
            return {"ok": False, "reason": exc.detail}
        return {"ok": True, **res}

    register_capability(CapabilityDef("profile.resolve", 1, MODULE_NAME, _profile_resolve))
    register_capability(CapabilityDef("participant.resolve", 1, MODULE_NAME, _participant_resolve))
    register_capability(CapabilityDef("project.create_from_template", 1, MODULE_NAME, _project_create_from_template))
    register_capability(CapabilityDef("projects.by_lead", 1, MODULE_NAME, _projects_by_lead))
    register_capability(CapabilityDef("projects.by_client", 1, MODULE_NAME, _projects_by_client))
    register_capability(CapabilityDef("project.payment_connection", 1, MODULE_NAME, _project_payment_connection))
    register_capability(CapabilityDef("project.commercial", 1, MODULE_NAME, _project_commercial))
    register_capability(CapabilityDef("tickets.for_invoice", 1, MODULE_NAME, _tickets_for_invoice))
    register_capability(CapabilityDef("ticket.refund", 1, MODULE_NAME, _ticket_refund))

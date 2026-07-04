"""EMS services (sprint-3/11) — Service-Repository layered, every query tenant-
scoped. The load-bearing logic: profile dedup + tier-1 status; template create
materializes the participant eligibility graph; project create-from-template
COPIES that graph (copy_scope); transitions ride the ONE status_machine.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.status import Status
from app.secrets import encrypt_secret
from app.services import status_machine
from app.status_engine.scoped import copy_scope, initial_scope_status, materialize_scope
from app.status_engine.scoped import ScopeSeedEdge, ScopeSeedStatus
from modules.ems.bootstrap import (
    PARTICIPANT_SCOPE_SEED_EDGES,
    PARTICIPANT_SCOPE_SEED_STATUSES,
)
from modules.ems.models import (
    PARTICIPANT_ENTITY,
    PROFILE_ENTITY,
    PROJECT_ENTITY,
    TICKET_ENTITY,
    Checkpoint,
    CheckpointLog,
    CapacityUnit,
    Profile,
    Project,
    ProjectProduct,
    ProjectProductZone,
    ProjectParticipant,
    Cart,
    CartItem,
    CapacityHold,
    ProjectTemplate,
    ProjectTemplateRole,
    ProjectTemplateSegment,
    ProjectType,
    Ticket,
    Venue,
    VenueSeat,
    VenueZone,
)


def _now():
    return datetime.now(timezone.utc)


def _participant_scope_edges() -> list:
    """Build ScopeSeedEdge list from PARTICIPANT_SCOPE_SEED_EDGES. Edges are
    4-tuples (manual) or 6-tuples (… trigger_mode, conditions) — the derived
    check-in auto-edge (sprint-4/03 R3-2). Conditions + trigger_mode ride along
    so a copied/materialized scope keeps the auto-edge."""
    out = []
    for edge in PARTICIPANT_SCOPE_SEED_EDGES:
        if len(edge) == 6:
            fk, tk, lbl, so, mode, conds = edge
            out.append(ScopeSeedEdge(fk, tk, lbl, so, trigger_mode=mode, conditions=conds))
        else:
            fk, tk, lbl, so = edge
            out.append(ScopeSeedEdge(fk, tk, lbl, so))
    return out


def _initial_unscoped(db: Session, entity_type: str, tenant_id: str) -> Optional[str]:
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id.is_(None),
            Status.is_initial.is_(True),
        )
        .order_by(Status.sort_order.asc())
        .first()
    )
    return row.id if row else None


def _paginate(query, page, page_size):
    total = query.count()
    rows = query.offset(page * page_size).limit(page_size).all()
    return rows, total


def _iso(v):
    return v.isoformat() if v else ""


# colKey → accessor(row) — the export column whitelist (id first for round-trip).
_PROFILE_COLS = {
    "id": lambda r: r.id,
    "email": lambda r: r.email,
    "fullName": lambda r: r.full_name or "",
    "phone": lambda r: r.phone or "",
    "country": lambda r: r.country or "",
    "organization": lambda r: r.organization or "",
    "title": lambda r: r.title or "",
    "createdAt": lambda r: _iso(r.created_at),
}
_PROJECT_COLS = {
    "id": lambda r: r.id,
    "title": lambda r: r.title,
    "brief": lambda r: r.brief or "",
    # Calendar dates → plain ISO date string (no time/tz).
    "startDate": lambda r: r.start_date.isoformat() if r.start_date else "",
    "endDate": lambda r: r.end_date.isoformat() if r.end_date else "",
    "createdAt": lambda r: _iso(r.created_at),
}
def _csv(columns, rows, colmap) -> str:
    import csv as _csvmod
    import io

    from app.import_engine.sanitize import sanitize_cell

    cols = [c for c in columns if c in colmap] or list(colmap.keys())
    buf = io.StringIO()
    w = _csvmod.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([sanitize_cell(colmap[c](r)) for c in cols])
    return buf.getvalue()


class ProfileService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {
        "fullName": Profile.full_name,
        "email": Profile.email,
        "organization": Profile.organization,
        "createdAt": Profile.created_at,
    }

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None):
        from sqlalchemy import func, or_

        q = self.db.query(Profile).filter(
            Profile.tenant_id == tenant_id, Profile.is_deleted.is_(trashed)
        )
        if ids:
            q = q.filter(Profile.id.in_(ids))
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(
                or_(func.lower(Profile.email).like(like), func.lower(Profile.full_name).like(like))
            )
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="asc"):
        q = self._filtered(tenant_id, search=search, trashed=trashed)
        col = self._SORT.get(sort_by, Profile.created_at)
        q = q.order_by(col.asc() if sort_dir == "asc" else col.desc())
        return _paginate(q, page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _PROFILE_COLS)

    def get(self, tenant_id, pid) -> Profile:
        p = (
            self.db.query(Profile)
            .filter(Profile.id == pid, Profile.tenant_id == tenant_id)
            .first()
        )
        if p is None:
            raise HTTPException(404, "Profile not found.")
        return p

    def create(self, tenant_id, data: dict) -> Profile:
        email = str(data["email"]).strip().lower()
        dup = (
            self.db.query(Profile.id)
            .filter(Profile.tenant_id == tenant_id, Profile.email == email)
            .first()
        )
        if dup is not None:
            raise HTTPException(409, "A profile with this email already exists.")
        p = Profile(
            tenant_id=tenant_id,
            email=email,
            phone=data.get("phone"),
            full_name=data.get("fullName"),
            country=data.get("country"),
            organization=data.get("organization"),
            title=data.get("title"),
            status_id=_initial_unscoped(self.db, PROFILE_ENTITY, tenant_id),
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def update(self, tenant_id, pid, data: dict) -> Profile:
        p = self.get(tenant_id, pid)
        changes: dict = {}
        for key, attr in [
            ("phone", "phone"), ("fullName", "full_name"), ("country", "country"),
            ("organization", "organization"), ("title", "title"),
        ]:
            if key in data and data[key] is not None:
                old = getattr(p, attr)
                if old != data[key]:
                    changes[attr] = {"from": old, "to": data[key]}
                setattr(p, attr, data[key])
        self.db.commit()
        self.db.refresh(p)
        # Re-derive on save so a field-vs-value auto edge re-fires (sprint-4/03).
        if changes:
            from app.workflow_engine.entity_events import notify_entity_event

            notify_entity_event(
                self.db, PROFILE_ENTITY, "updated", p,
                tenant_id=tenant_id, changes=changes,
            )
        return p

    def delete(self, tenant_id, pid) -> None:
        p = self.get(tenant_id, pid)
        p.is_deleted = True
        p.deleted_at = _now()
        self.db.commit()

    def transition(self, tenant_id, pid, to_status_id, actor) -> Profile:
        p = self.get(tenant_id, pid)
        status_machine.transition(
            self.db, PROFILE_ENTITY, p, to_status_id, actor, tenant_id=tenant_id
        )
        self.db.commit()
        self.db.refresh(p)
        return p


class ProjectTypeService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id, *, page=0, page_size=25):
        q = self.db.query(ProjectType).filter(
            ProjectType.tenant_id == tenant_id, ProjectType.is_deleted.is_(False)
        )
        return _paginate(q.order_by(ProjectType.name.asc()), page, page_size)

    def create(self, tenant_id, data) -> ProjectType:
        t = ProjectType(tenant_id=tenant_id, name=data["name"], description=data.get("description"))
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def get(self, tenant_id, tid) -> ProjectType:
        t = self.db.query(ProjectType).filter(
            ProjectType.id == tid, ProjectType.tenant_id == tenant_id,
            ProjectType.is_deleted.is_(False),
        ).first()
        if t is None:
            raise HTTPException(404, "Event type not found.")
        return t

    def update(self, tenant_id, tid, data: dict) -> ProjectType:
        t = self.get(tenant_id, tid)
        if data.get("name") is not None:
            t.name = data["name"]
        if "description" in data:
            t.description = data["description"]
        self.db.commit()
        self.db.refresh(t)
        return t

    def delete(self, tenant_id, tid) -> None:
        t = self.get(tenant_id, tid)
        # Guard: a type still owning templates can't be removed (would orphan them).
        in_use = (
            self.db.query(ProjectTemplate.id)
            .filter(
                ProjectTemplate.tenant_id == tenant_id,
                ProjectTemplate.type_id == tid,
                ProjectTemplate.is_deleted.is_(False),
            )
            .first()
        )
        if in_use is not None:
            raise HTTPException(409, "This event type still has templates. Delete or move them first.")
        t.is_deleted = True
        self.db.commit()


class ProjectTemplateService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id, *, type_id=None, page=0, page_size=25):
        q = self.db.query(ProjectTemplate).filter(
            ProjectTemplate.tenant_id == tenant_id, ProjectTemplate.is_deleted.is_(False)
        )
        if type_id:
            q = q.filter(ProjectTemplate.type_id == type_id)
        return _paginate(q.order_by(ProjectTemplate.name.asc()), page, page_size)

    def get(self, tenant_id, tid) -> ProjectTemplate:
        t = self.db.query(ProjectTemplate).filter(
            ProjectTemplate.id == tid, ProjectTemplate.tenant_id == tenant_id,
            ProjectTemplate.is_deleted.is_(False),
        ).first()
        if t is None:
            raise HTTPException(404, "Event template not found.")
        return t

    def update(self, tenant_id, tid, data: dict) -> ProjectTemplate:
        t = self.get(tenant_id, tid)
        if data.get("name") is not None:
            t.name = data["name"]
        if "description" in data:
            t.description = data["description"]
        self.db.commit()
        self.db.refresh(t)
        return t

    def delete(self, tenant_id, tid) -> None:
        t = self.get(tenant_id, tid)
        # Guard: a template that already spawned events can't be removed (those
        # events keep their copied eligibility graph; the template stays for audit).
        in_use = (
            self.db.query(Project.id)
            .filter(
                Project.tenant_id == tenant_id,
                Project.template_id == tid,
                Project.is_deleted.is_(False),
            )
            .first()
        )
        if in_use is not None:
            raise HTTPException(409, "This event template is used by existing events and can't be deleted.")
        t.is_deleted = True
        self.db.commit()

    # ── roles / segments (template-owned, shared by participants; AC-11-01) ──

    def _child_model(self, kind: str):
        return ProjectTemplateRole if kind == "role" else ProjectTemplateSegment

    def list_children(self, tenant_id, template_id, kind: str):
        self.get(tenant_id, template_id)  # tenant + existence guard
        model = self._child_model(kind)
        return (
            self.db.query(model)
            .filter(model.tenant_id == tenant_id, model.template_id == template_id)
            .order_by(model.name.asc())
            .all()
        )

    def add_child(self, tenant_id, template_id, kind: str, name: str):
        self.get(tenant_id, template_id)
        model = self._child_model(kind)
        row = model(tenant_id=tenant_id, template_id=template_id, name=name)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_child(self, tenant_id, template_id, kind: str, child_id: str):
        self.get(tenant_id, template_id)
        model = self._child_model(kind)
        row = (
            self.db.query(model)
            .filter(
                model.id == child_id,
                model.tenant_id == tenant_id,
                model.template_id == template_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(404, f"{kind.capitalize()} not found.")
        self.db.delete(row)
        self.db.commit()

    def create(self, tenant_id, data) -> ProjectTemplate:
        # validate type belongs to tenant
        ProjectTypeService(self.db).get(tenant_id, data["typeId"])
        t = ProjectTemplate(
            tenant_id=tenant_id,
            type_id=data["typeId"],
            name=data["name"],
            description=data.get("description"),
        )
        self.db.add(t)
        self.db.flush()
        # Materialize the template's default eligibility flow (scope=template_id).
        materialize_scope(
            self.db,
            PARTICIPANT_ENTITY,
            tenant_id,
            t.id,
            [ScopeSeedStatus(k, l, c, s, f) for (k, l, c, s, f) in PARTICIPANT_SCOPE_SEED_STATUSES],
            _participant_scope_edges(),
        )
        self.db.commit()
        self.db.refresh(t)
        return t


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"title": Project.title, "createdAt": Project.created_at}

    def _filtered(self, tenant_id, *, search=None, ids=None):
        from sqlalchemy import func

        q = self.db.query(Project).filter(
            Project.tenant_id == tenant_id, Project.is_deleted.is_(False)
        )
        if ids:
            q = q.filter(Project.id.in_(ids))
        if search:
            q = q.filter(func.lower(Project.title).like(f"%{search.lower()}%"))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, sort_by=None, sort_dir="desc"):
        q = self._filtered(tenant_id, search=search)
        col = self._SORT.get(sort_by, Project.created_at)
        q = q.order_by(col.asc() if sort_dir == "asc" else col.desc())
        return _paginate(q, page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None):
        rows = self._filtered(tenant_id, search=search, ids=ids).all()
        return _csv(columns, rows, _PROJECT_COLS)

    def get(self, tenant_id, pid) -> Project:
        p = self.db.query(Project).filter(
            Project.id == pid, Project.tenant_id == tenant_id
        ).first()
        if p is None:
            raise HTTPException(404, "Event not found.")
        return p

    def create(self, tenant_id, data) -> Project:
        template = ProjectTemplateService(self.db).get(tenant_id, data["templateId"])
        p = Project(
            tenant_id=tenant_id,
            template_id=template.id,
            type_id=template.type_id,
            title=data["title"],
            brief=data.get("brief"),
            status_id=_initial_unscoped(self.db, PROJECT_ENTITY, tenant_id),
        )
        self.db.add(p)
        self.db.flush()
        # Copy the TEMPLATE's eligibility graph into the project's own scope (D4).
        copy_scope(self.db, PARTICIPANT_ENTITY, tenant_id, template.id, p.id)
        self.db.commit()
        self.db.refresh(p)
        return p

    # camelCase wire key → model attr. Immutable fields (template/type/client/
    # status) are deliberately absent (Slice 5) — never mutated via update.
    _UPDATE_FIELDS = {
        "title": "title",
        "brief": "brief",
        "notes": "notes",
        "domainName": "domain_name",
        "startDate": "start_date",
        "endDate": "end_date",
        "eventValidityEnd": "event_validity_end",
        # Cluster F slice 4 (AC-07-45) — commercial mode + agency fee config.
        "commercialMode": "commercial_mode",
        "feeType": "fee_type",
        "feeValue": "fee_value",
        "paymentConnectionId": "payment_connection_id",
    }

    def update(self, tenant_id, pid, data: dict) -> Project:
        """PATCH-merge the editable fields. ``data`` carries only the keys the
        caller SET (absent = keep, explicit None = clear). Dates are calendar
        dates; the resulting start/end/validity order is validated (422)."""
        p = self.get(tenant_id, pid)
        if "title" in data and not (data["title"] or "").strip():
            raise HTTPException(422, "Title is required.")
        # Commercial config validation (AC-07-45).
        if data.get("commercialMode") not in (None, "SELF_RUN", "AGENCY"):
            raise HTTPException(422, "Commercial mode must be SELF_RUN or AGENCY.")
        if "feeType" in data and data["feeType"] not in (None, "PERCENT", "FLAT", "PER_TICKET"):
            raise HTTPException(422, "Fee type must be PERCENT, FLAT or PER_TICKET.")
        changes: dict = {}
        for key, attr in self._UPDATE_FIELDS.items():
            if key in data:
                old = getattr(p, attr)
                new = data[key]
                if old != new:
                    changes[attr] = {"from": old, "to": new}
                setattr(p, attr, new)
        # Ordering on the RESULTING state (calendar dates) — only when both bounds set.
        if p.start_date and p.end_date and p.end_date < p.start_date:
            raise HTTPException(422, "End date must be on or after the start date.")
        if p.end_date and p.event_validity_end and p.event_validity_end < p.end_date:
            raise HTTPException(
                422, "Event validity end must be on or after the end date."
            )
        self.db.commit()
        self.db.refresh(p)
        # Emit so a field-vs-value auto edge (e.g. "End Date after X") re-derives
        # the event on SAVE — event-driven, not the time sweep (sprint-4/03). The
        # repo committed, so use the emit+dispatch pattern; fully failure-isolated.
        if changes:
            from app.workflow_engine.entity_events import notify_entity_event

            notify_entity_event(
                self.db, PROJECT_ENTITY, "updated", p,
                tenant_id=tenant_id, changes=changes,
            )
        return p

    def transition(self, tenant_id, pid, to_status_id, actor) -> Project:
        p = self.get(tenant_id, pid)
        status_machine.transition(
            self.db, PROJECT_ENTITY, p, to_status_id, actor, tenant_id=tenant_id
        )
        self.db.commit()
        self.db.refresh(p)
        return p

    def create_for_lead(self, tenant_id, *, template_id, title, client_id, lead_id) -> Project:
        """Backs the CRM lead→event capability (project.create_from_template). Spawns
        a Project from a template, copies the eligibility graph, stamps the
        originating lead/client soft-refs. The caller (capability) owns the commit."""
        template = ProjectTemplateService(self.db).get(tenant_id, template_id)
        p = Project(
            tenant_id=tenant_id,
            template_id=template.id,
            type_id=template.type_id,
            title=title or "Event",
            client_id=client_id,
            lead_id=lead_id,
            status_id=_initial_unscoped(self.db, PROJECT_ENTITY, tenant_id),
        )
        self.db.add(p)
        self.db.flush()
        copy_scope(self.db, PARTICIPANT_ENTITY, tenant_id, template.id, p.id)
        return p


class ParticipantService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id, project_id, *, page=0, page_size=25):
        ProjectService(self.db).get(tenant_id, project_id)  # scope guard
        q = self.db.query(ProjectParticipant).filter(
            ProjectParticipant.tenant_id == tenant_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.is_deleted.is_(False),
        )
        return _paginate(q.order_by(ProjectParticipant.created_at.desc()), page, page_size)

    def _validate_role_segment(self, tenant_id, project, role_id, segment_id):
        """Role/segment must belong to the project's TEMPLATE (shared, not copied
        — AC-11-04). Reject a cross-template/foreign id (same guard class as the
        polymorphic target_id rule)."""
        if role_id is not None:
            ok = (
                self.db.query(ProjectTemplateRole.id)
                .filter(
                    ProjectTemplateRole.id == role_id,
                    ProjectTemplateRole.tenant_id == tenant_id,
                    ProjectTemplateRole.template_id == project.template_id,
                )
                .first()
            )
            if ok is None:
                raise HTTPException(422, "Role does not belong to this event's template.")
        if segment_id is not None:
            ok = (
                self.db.query(ProjectTemplateSegment.id)
                .filter(
                    ProjectTemplateSegment.id == segment_id,
                    ProjectTemplateSegment.tenant_id == tenant_id,
                    ProjectTemplateSegment.template_id == project.template_id,
                )
                .first()
            )
            if ok is None:
                raise HTTPException(422, "Segment does not belong to this event's template.")

    def _assert_profile_eligible(self, tenant_id, profile_id):
        """Tier-1 gate (status engine): a profile whose status blocks access
        (Suspended/Blacklisted) can't be registered for an event. The status
        engine — not ad-hoc flags — decides eligibility."""
        prof = (
            self.db.query(Profile)
            .filter(
                Profile.id == profile_id,
                Profile.tenant_id == tenant_id,
                Profile.is_deleted.is_(False),
            )
            .first()
        )
        if prof is None:
            raise HTTPException(422, "Profile not found.")
        if prof.status_id:
            status = (
                self.db.query(Status)
                .filter(Status.id == prof.status_id, Status.tenant_id == tenant_id)
                .first()
            )
            if status is not None and status.blocks_access:
                raise HTTPException(
                    422,
                    f"{prof.full_name or prof.email} is {status.label} and can't be registered for an event.",
                )

    def add(self, tenant_id, project_id, data) -> ProjectParticipant:
        project = ProjectService(self.db).get(tenant_id, project_id)
        self._assert_profile_eligible(tenant_id, data["profileId"])
        # one row per (profile, project) v1
        dup = (
            self.db.query(ProjectParticipant.id)
            .filter(
                ProjectParticipant.tenant_id == tenant_id,
                ProjectParticipant.profile_id == data["profileId"],
                ProjectParticipant.project_id == project_id,
            )
            .first()
        )
        if dup is not None:
            raise HTTPException(409, "This profile is already registered for the event.")
        self._validate_role_segment(tenant_id, project, data.get("roleId"), data.get("segmentId"))
        initial = initial_scope_status(self.db, PARTICIPANT_ENTITY, tenant_id, project_id)
        pp = ProjectParticipant(
            tenant_id=tenant_id,
            profile_id=data["profileId"],
            project_id=project_id,
            role_id=data.get("roleId"),
            segment_id=data.get("segmentId"),
            status_id=initial.id if initial else None,
        )
        self.db.add(pp)
        self.db.commit()
        self.db.refresh(pp)
        # AUTO-derive the participant persona, project-scoped (sprint-4/06 0b,
        # AC-06-22 AUTO path). Failure-isolated — a persona-grant hiccup (e.g.
        # EMS not seeding the persona on an old tenant) never breaks participant
        # add. grant_persona resolves the persona by (tenant, key); missing = no-op.
        try:
            from modules.ems.models import PERSONA_GRANT_AUTO, PERSONA_SCOPE_PROJECT
            from modules.ems.persona_service import grant_persona

            grant_persona(
                self.db,
                tenant_id,
                pp.profile_id,
                "participant",
                PERSONA_SCOPE_PROJECT,
                project_id,
                PERSONA_GRANT_AUTO,
            )
        except Exception:  # noqa: BLE001 — never break participant add
            self.db.rollback()
        # Re-derive the owning project (sprint-4/03 AC-03-11): a participant-count
        # auto edge fires when this push tips the count over its threshold. emit +
        # dispatch (the internally-committing pattern); failure-isolated.
        from app.workflow_engine.entity_events import notify_entity_event

        notify_entity_event(
            self.db, PARTICIPANT_ENTITY, "created", pp, tenant_id=tenant_id
        )
        return pp

    def _get(self, tenant_id, project_id, pp_id) -> ProjectParticipant:
        pp = (
            self.db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.id == pp_id,
                ProjectParticipant.tenant_id == tenant_id,
                ProjectParticipant.project_id == project_id,
            )
            .first()
        )
        if pp is None:
            raise HTTPException(404, "Participant not found.")
        return pp

    def update(self, tenant_id, project_id, pp_id, data) -> ProjectParticipant:
        project = ProjectService(self.db).get(tenant_id, project_id)
        pp = self._get(tenant_id, project_id, pp_id)
        self._validate_role_segment(
            tenant_id, project, data.get("roleId"), data.get("segmentId")
        )
        if "roleId" in data:
            pp.role_id = data["roleId"]
        if "segmentId" in data:
            pp.segment_id = data["segmentId"]
        self.db.commit()
        self.db.refresh(pp)
        return pp

    def transition(self, tenant_id, project_id, pp_id, to_status_id, actor) -> ProjectParticipant:
        pp = (
            self.db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.id == pp_id,
                ProjectParticipant.tenant_id == tenant_id,
                ProjectParticipant.project_id == project_id,
            )
            .first()
        )
        if pp is None:
            raise HTTPException(404, "Participant not found.")
        status_machine.transition(
            self.db, PARTICIPANT_ENTITY, pp, to_status_id, actor, tenant_id=tenant_id
        )
        self.db.commit()
        self.db.refresh(pp)
        return pp


# ── Cluster D (sprint-4/05) — Venue master + Offerings + capacity ────────────


def _row_label(i: int, mode: str) -> str:
    """A,B,C… (alpha) or 1,2,3… (numeric) — mirrors the frontend generator."""
    if mode == "numeric":
        return str(i + 1)
    n, s = i, ""
    while True:
        s = chr(65 + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def _tenant_currency(db: Session, tenant_id: str) -> str:
    """The tenant's default currency (catalog/quotation default); app fallback
    when the tenant has no override row."""
    from app.models.tenant_settings import DEFAULT_CURRENCY, TenantSettings

    row = db.query(TenantSettings).filter(TenantSettings.tenant_id == tenant_id).first()
    return (row.default_currency if row and row.default_currency else None) or DEFAULT_CURRENCY


def _product_name(db: Session, tenant_id: str, product_id: str) -> str:
    """Resolve a core-catalog product name (soft-ref, tenant-scoped)."""
    from app.models.catalog import Product

    row = (
        db.query(Product)
        .filter(Product.id == product_id, Product.tenant_id == tenant_id)
        .first()
    )
    return row.name if row else ""


def resolve_public_event(db: Session, tenant_slug: str, project_id: str):
    """Resolve (tenant, project) from a public slug + id; uniform 404 (no
    enumeration). Lives in the service layer so the public router stays query-free."""
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if tenant is None:
        raise HTTPException(404, "Not found.")
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.tenant_id == tenant.id, Project.is_deleted.is_(False))
        .first()
    )
    if project is None:
        raise HTTPException(404, "Not found.")
    return tenant, project


class VenueService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"name": Venue.name, "createdAt": Venue.created_at}

    def _filtered(self, tenant_id, *, search=None, trashed=False):
        q = self.db.query(Venue).filter(
            Venue.tenant_id == tenant_id, Venue.is_deleted.is_(trashed)
        )
        if search:
            s = f"%{search.lower()}%"
            q = q.filter(
                func.lower(Venue.name).like(s) | func.lower(func.coalesce(Venue.address, "")).like(s)
            )
        return q

    def _enrich(self, v: Venue) -> Venue:
        v.zoneCount = (
            self.db.query(VenueZone).filter(VenueZone.venue_id == v.id).count()
        )
        v.seatCount = (
            self.db.query(VenueSeat).filter(VenueSeat.venue_id == v.id).count()
        )
        return v

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="desc"):
        q = self._filtered(tenant_id, search=search, trashed=trashed)
        col = self._SORT.get(sort_by, Venue.created_at)
        q = q.order_by(col.asc() if sort_dir == "asc" else col.desc())
        rows, total = _paginate(q, page, page_size)
        return [self._enrich(r) for r in rows], total

    def get(self, tenant_id, vid) -> Venue:
        v = self.db.query(Venue).filter(Venue.id == vid, Venue.tenant_id == tenant_id).first()
        if v is None:
            raise HTTPException(404, "Venue not found.")
        return self._enrich(v)

    def create(self, tenant_id, data: dict) -> Venue:
        v = Venue(
            tenant_id=tenant_id,
            name=data["name"],
            address=data.get("address"),
            capacity=data.get("capacity"),
        )
        self.db.add(v)
        self.db.commit()
        self.db.refresh(v)
        return self._enrich(v)

    def update(self, tenant_id, vid, data: dict) -> Venue:
        v = self.get(tenant_id, vid)
        for key in ("name", "address", "capacity"):
            if key in data:
                setattr(v, key, data[key])
        self.db.commit()
        self.db.refresh(v)
        return self._enrich(v)

    def delete(self, tenant_id, vid) -> None:
        v = self.get(tenant_id, vid)
        v.is_deleted = True
        v.deleted_at = _now()
        self.db.commit()

    # ── zones ──
    def _zone(self, tenant_id, zone_id) -> VenueZone:
        z = (
            self.db.query(VenueZone)
            .filter(VenueZone.id == zone_id, VenueZone.tenant_id == tenant_id)
            .first()
        )
        if z is None:
            raise HTTPException(404, "Zone not found.")
        return z

    def list_zones(self, tenant_id, venue_id):
        self.get(tenant_id, venue_id)  # tenant + existence guard
        zones = (
            self.db.query(VenueZone)
            .filter(VenueZone.tenant_id == tenant_id, VenueZone.venue_id == venue_id)
            .order_by(VenueZone.sort.asc())
            .all()
        )
        for z in zones:
            z.seatCount = self.db.query(VenueSeat).filter(VenueSeat.zone_id == z.id).count()
        return zones

    def create_zone(self, tenant_id, venue_id, data: dict) -> VenueZone:
        self.get(tenant_id, venue_id)
        sort = (
            self.db.query(VenueZone)
            .filter(VenueZone.venue_id == venue_id)
            .count()
        )
        z = VenueZone(
            tenant_id=tenant_id,
            venue_id=venue_id,
            name=data["name"],
            kind=data.get("kind", "section"),
            sort=sort,
        )
        self.db.add(z)
        self.db.commit()
        self.db.refresh(z)
        z.seatCount = 0
        return z

    def update_zone(self, tenant_id, zone_id, data: dict) -> VenueZone:
        z = self._zone(tenant_id, zone_id)
        for key in ("name", "kind", "sort"):
            if key in data and data[key] is not None:
                setattr(z, key, data[key])
        self.db.commit()
        self.db.refresh(z)
        z.seatCount = self.db.query(VenueSeat).filter(VenueSeat.zone_id == z.id).count()
        return z

    def delete_zone(self, tenant_id, zone_id) -> None:
        z = self._zone(tenant_id, zone_id)
        self.db.query(VenueSeat).filter(VenueSeat.zone_id == z.id).delete(synchronize_session=False)
        self.db.delete(z)
        self.db.commit()

    # ── seats ──
    def list_seats(self, tenant_id, venue_id):
        self.get(tenant_id, venue_id)
        return (
            self.db.query(VenueSeat)
            .filter(VenueSeat.tenant_id == tenant_id, VenueSeat.venue_id == venue_id)
            .order_by(VenueSeat.y.asc(), VenueSeat.x.asc())
            .all()
        )

    def generate_seats(self, tenant_id, data: dict):
        z = self._zone(tenant_id, data["zoneId"])
        rows = int(data["rows"])
        per_row = int(data["perRow"])
        if rows < 1 or per_row < 1:
            raise HTTPException(422, "Rows and seats per row must be positive.")
        mode = data.get("rowLabels", "alpha")
        start = int(data.get("startNumber", 1))
        section = data.get("section") or z.name
        created = []
        for r in range(rows):
            rl = _row_label(r, mode)
            for c in range(per_row):
                num = str(start + c)
                # Prefix the zone/section so labels are unambiguous across zones
                # (two zones can both have a row C seat 8 → "Main·C8" vs "VIP·C8").
                seat = VenueSeat(
                    tenant_id=tenant_id,
                    venue_id=z.venue_id,
                    zone_id=z.id,
                    section=section,
                    row=rl,
                    number=num,
                    label=f"{section}·{rl}{num}",
                    x=c * 32,
                    y=r * 32,
                )
                self.db.add(seat)
                created.append(seat)
        self.db.commit()
        for s in created:
            self.db.refresh(s)
        return created

    def clear_zone_seats(self, tenant_id, zone_id) -> None:
        z = self._zone(tenant_id, zone_id)
        self.db.query(VenueSeat).filter(VenueSeat.zone_id == z.id).delete(synchronize_session=False)
        self.db.commit()


class OfferingService:
    def __init__(self, db: Session):
        self.db = db

    def _zone_ids(self, offering_id):
        return [
            r.zone_id
            for r in self.db.query(ProjectProductZone)
            .filter(ProjectProductZone.project_product_id == offering_id)
            .all()
        ]

    def _enrich(self, tenant_id, o: ProjectProduct) -> ProjectProduct:
        o.productName = _product_name(self.db, tenant_id, o.product_id)
        o.zoneIds = self._zone_ids(o.id)
        units = self.db.query(CapacityUnit).filter(CapacityUnit.project_product_id == o.id)
        o.unitCount = units.count()
        o.soldCount = units.filter(CapacityUnit.status == "sold").count()
        o.heldCount = units.filter(CapacityUnit.status == "held").count()
        return o

    def list(self, tenant_id, project_id):
        rows = (
            self.db.query(ProjectProduct)
            .filter(
                ProjectProduct.tenant_id == tenant_id,
                ProjectProduct.project_id == project_id,
            )
            .order_by(ProjectProduct.created_at.asc())
            .all()
        )
        return [self._enrich(tenant_id, r) for r in rows]

    def get(self, tenant_id, project_id, offering_id) -> ProjectProduct:
        o = (
            self.db.query(ProjectProduct)
            .filter(
                ProjectProduct.id == offering_id,
                ProjectProduct.tenant_id == tenant_id,
                ProjectProduct.project_id == project_id,
            )
            .first()
        )
        if o is None:
            raise HTTPException(404, "Offering not found.")
        return self._enrich(tenant_id, o)

    def _write_zones(self, tenant_id, offering_id, zone_ids):
        self.db.query(ProjectProductZone).filter(
            ProjectProductZone.project_product_id == offering_id
        ).delete(synchronize_session=False)
        for zid in zone_ids or []:
            self.db.add(
                ProjectProductZone(
                    tenant_id=tenant_id, project_product_id=offering_id, zone_id=zid
                )
            )

    def _link_venue(self, tenant_id, project_id, venue_id):
        if not venue_id:
            return
        from modules.ems.models import ProjectVenue

        exists = (
            self.db.query(ProjectVenue)
            .filter(
                ProjectVenue.tenant_id == tenant_id,
                ProjectVenue.project_id == project_id,
                ProjectVenue.venue_id == venue_id,
            )
            .first()
        )
        if not exists:
            self.db.add(
                ProjectVenue(tenant_id=tenant_id, project_id=project_id, venue_id=venue_id)
            )

    def create(self, tenant_id, project_id, data: dict) -> ProjectProduct:
        o = ProjectProduct(
            tenant_id=tenant_id,
            project_id=project_id,
            product_id=data["productId"],
            price=data.get("price"),
            currency=data.get("currency") or _tenant_currency(self.db, tenant_id),
            tax_rate=data.get("taxRate", 0) or 0,
            capacity=data.get("capacity", 0) or 0,
            allocation_mode=data.get("allocationMode", "GA"),
            valid_from=data.get("validFrom"),
            valid_until=data.get("validUntil"),
            grants_segment_id=data.get("grantsSegmentId"),
            grants_role_id=data.get("grantsRoleId"),
            max_tickets_per_attendee=data.get("maxTicketsPerAttendee"),
            venue_id=data.get("venueId"),
        )
        self.db.add(o)
        self.db.flush()
        self._write_zones(tenant_id, o.id, data.get("zoneIds"))
        self._link_venue(tenant_id, project_id, o.venue_id)
        self.db.commit()
        self.db.refresh(o)
        return self._enrich(tenant_id, o)

    _FIELDS = {
        "productId": "product_id",
        "price": "price",
        "currency": "currency",
        "taxRate": "tax_rate",
        "capacity": "capacity",
        "allocationMode": "allocation_mode",
        "validFrom": "valid_from",
        "validUntil": "valid_until",
        "grantsSegmentId": "grants_segment_id",
        "grantsRoleId": "grants_role_id",
        "maxTicketsPerAttendee": "max_tickets_per_attendee",
        "venueId": "venue_id",
    }

    def update(self, tenant_id, project_id, offering_id, data: dict) -> ProjectProduct:
        o = self.get(tenant_id, project_id, offering_id)
        for key, attr in self._FIELDS.items():
            if key in data:
                setattr(o, attr, data[key])
        if "zoneIds" in data and data["zoneIds"] is not None:
            self._write_zones(tenant_id, o.id, data["zoneIds"])
        self._link_venue(tenant_id, project_id, o.venue_id)
        self.db.commit()
        self.db.refresh(o)
        return self._enrich(tenant_id, o)

    def delete(self, tenant_id, project_id, offering_id) -> None:
        o = self.get(tenant_id, project_id, offering_id)
        self.db.query(CapacityUnit).filter(
            CapacityUnit.project_product_id == o.id
        ).delete(synchronize_session=False)
        self.db.query(ProjectProductZone).filter(
            ProjectProductZone.project_product_id == o.id
        ).delete(synchronize_session=False)
        self.db.delete(o)
        self.db.commit()

    def mint_capacity_units(self, tenant_id, project_id, offering_id):
        o = self.get(tenant_id, project_id, offering_id)
        if o.allocation_mode != "RESERVED" or not o.venue_id:
            raise HTTPException(422, "Only RESERVED offerings with a venue mint seats.")
        zone_ids = self._zone_ids(o.id)
        if not zone_ids:
            raise HTTPException(422, "Pick at least one zone before minting seats.")
        # re-mint = clear existing free units (sold/held kept — never destroy a sale)
        self.db.query(CapacityUnit).filter(
            CapacityUnit.project_product_id == o.id, CapacityUnit.status == "free"
        ).delete(synchronize_session=False)
        taken_seat_ids = {
            u.venue_seat_id
            for u in self.db.query(CapacityUnit).filter(
                CapacityUnit.project_product_id == o.id
            )
        }
        seats = (
            self.db.query(VenueSeat)
            .filter(
                VenueSeat.tenant_id == tenant_id,
                VenueSeat.venue_id == o.venue_id,
                VenueSeat.zone_id.in_(zone_ids),
            )
            .all()
        )
        zone_names = {z.id: z.name for z in self.db.query(VenueZone).filter(VenueZone.venue_id == o.venue_id)}
        for s in seats:
            if s.id in taken_seat_ids:
                continue
            self.db.add(
                CapacityUnit(
                    tenant_id=tenant_id,
                    project_product_id=o.id,
                    venue_seat_id=s.id,
                    label=s.label,
                    section=s.section,
                    row=s.row,
                    number=s.number,
                    zone=zone_names.get(s.zone_id),
                    x=s.x,
                    y=s.y,
                    status="free",
                )
            )
        # capacity = the live unit count (autoflush makes the just-added units
        # visible to count()); the previous arithmetic double-counted them.
        o.capacity = (
            self.db.query(CapacityUnit).filter(CapacityUnit.project_product_id == o.id).count()
        )
        self.db.commit()
        return self.list_capacity_units(tenant_id, project_id, offering_id)

    def list_capacity_units(self, tenant_id, project_id, offering_id):
        self.get(tenant_id, project_id, offering_id)  # tenant + scope guard
        return (
            self.db.query(CapacityUnit)
            .filter(CapacityUnit.project_product_id == offering_id)
            .order_by(CapacityUnit.y.asc(), CapacityUnit.x.asc())
            .all()
        )


# ── Cluster D slice 2 (sprint-4/05) — checkout / confirm ─────────────────────


class CheckoutService:
    """Confirm a registration: find-or-create Profile → participant (copy grants)
    → signed-QR ticket → ONE Draft invoice via finance.create_invoice@1. The whole
    thing runs in ONE session/commit (ems tickets + finance invoice atomic, R3-1).
    Comp (comp=True) skips the invoice (ticket.invoice_id stays NULL)."""

    def __init__(self, db: Session):
        self.db = db

    def _find_or_create_profile(self, tenant_id, attendee: dict) -> Profile:
        email = str(attendee.get("email", "")).strip().lower()
        if not email:
            raise HTTPException(422, "Each attendee needs an email.")
        p = (
            self.db.query(Profile)
            .filter(Profile.tenant_id == tenant_id, Profile.email == email, Profile.is_deleted.is_(False))
            .first()
        )
        if p is not None:
            return p
        p = Profile(
            tenant_id=tenant_id,
            email=email,
            full_name=attendee.get("name"),
            phone=attendee.get("phone"),
            status_id=_initial_unscoped(self.db, PROFILE_ENTITY, tenant_id),
        )
        self.db.add(p)
        self.db.flush()
        return p

    def _get_or_create_participant(self, tenant_id, project_id, profile: Profile, offering: ProjectProduct) -> ProjectParticipant:
        # blocks_access profiles can't register (foolproof-UI + real boundary)
        if profile.status_id:
            st = self.db.query(Status).filter(Status.id == profile.status_id).first()
            if st is not None and st.blocks_access:
                raise HTTPException(422, "This profile is suspended and cannot register.")
        existing = (
            self.db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.tenant_id == tenant_id,
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.profile_id == profile.id,
            )
            .first()
        )
        if existing is not None:
            return existing
        initial = initial_scope_status(self.db, PARTICIPANT_ENTITY, tenant_id, project_id)
        pp = ProjectParticipant(
            tenant_id=tenant_id,
            project_id=project_id,
            profile_id=profile.id,
            role_id=offering.grants_role_id,  # copy grants (Q3)
            segment_id=offering.grants_segment_id,
            status_id=initial.id if initial else None,
        )
        self.db.add(pp)
        self.db.flush()
        return pp

    def confirm(self, tenant_id, project_id, items: list, *, comp: bool = False) -> dict:
        """items: [{offeringId, attendee:{name,email,phone}, capacityUnitId?}]."""
        ProjectService(self.db).get(tenant_id, project_id)  # tenant + existence guard
        if not items:
            raise HTTPException(422, "Nothing to confirm.")
        offerings: dict = {}
        tickets: list = []
        emails: set = set()
        first_profile: Optional[Profile] = None
        for it in items:
            off_id = it["offeringId"]
            if off_id not in offerings:
                offerings[off_id] = OfferingService(self.db).get(tenant_id, project_id, off_id)
            offering = offerings[off_id]
            profile = self._find_or_create_profile(tenant_id, it.get("attendee", {}))
            emails.add(profile.email)
            if first_profile is None:
                first_profile = profile
            participant = self._get_or_create_participant(tenant_id, project_id, profile, offering)
            issued = _initial_unscoped(self.db, TICKET_ENTITY, tenant_id)
            t = Ticket(
                tenant_id=tenant_id,
                project_id=project_id,
                project_product_id=off_id,
                capacity_unit_id=it.get("capacityUnitId"),
                attendee_profile_id=profile.id,
                participant_id=participant.id,
                status="issued",  # legacy mirror, kept in sync with status_id
                status_id=issued,
            )
            self.db.add(t)
            self.db.flush()
            # signed/opaque QR carrying a rotation nonce; slice-3 scan validates
            # the nonce (a transfer rotates it → the old QR ciphertext dies).
            t.qr_nonce = uuid.uuid4().hex
            t.qr_token = encrypt_secret({"t": t.id, "n": t.qr_nonce})
            # RESERVED seat → mark sold + stamp occupancy
            if it.get("capacityUnitId"):
                unit = (
                    self.db.query(CapacityUnit)
                    .filter(
                        CapacityUnit.id == it["capacityUnitId"],
                        CapacityUnit.tenant_id == tenant_id,
                        CapacityUnit.project_product_id == off_id,  # no cross-offering mark-sold
                    )
                    .first()
                )
                if unit is not None:
                    unit.status = "sold"
                    unit.participant_id = participant.id
                    unit.held_until = None
                    unit.held_by_cart_id = None
            tickets.append((t, offering, profile))

        invoice = None
        if not comp:
            invoice = self._create_invoice(
                tenant_id, project_id, [(t, o) for t, o, _ in tickets], first_profile
            )
            if invoice:
                for t, _, _ in tickets:
                    t.invoice_id = invoice["id"]
        self.db.commit()
        return {
            "orderRef": f"REG-{tickets[0][0].id[:6].upper()}" if tickets else "REG-000000",
            "invoiceId": invoice["id"] if invoice else None,
            "total": invoice["total"] if invoice else 0,
            "currency": invoice["currency"] if invoice else (tickets[0][1].currency if tickets else None),
            "ticketCount": len(tickets),
            "confirmationEmails": sorted(emails),
            # Per-ticket QR for the Done screen (AC-05-TKT-02) — rendered straight
            # from the live confirm result (signed/opaque token).
            "tickets": [
                {
                    "ticketId": t.id,
                    "qrToken": t.qr_token,
                    "attendeeName": profile.full_name if profile else None,
                    "offeringName": _product_name(self.db, tenant_id, offering.product_id),
                }
                for t, offering, profile in tickets
            ],
        }

    def _create_invoice(self, tenant_id, project_id, tickets, bill_profile: Optional[Profile]):
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "finance.create_invoice", 1)
        if handler is None:
            raise HTTPException(409, "The Finance module is not installed for this workspace.")
        # group tickets by offering → one line per offering (qty)
        by_off: dict = {}
        for t, offering in tickets:
            agg = by_off.setdefault(offering.id, {"offering": offering, "qty": 0})
            agg["qty"] += 1
        lines = [
            {
                "projectProductId": off_id,
                "description": _product_name(self.db, tenant_id, agg["offering"].product_id),
                "qty": agg["qty"],
                "unitPrice": agg["offering"].price or 0,
                "taxRate": agg["offering"].tax_rate or 0,
            }
            for off_id, agg in by_off.items()
        ]
        return handler(
            self.db,
            tenant_id,
            {
                "projectId": project_id,
                "billToType": "Profile",
                "billToId": bill_profile.id if bill_profile else "",
                "lines": lines,
            },
        )


# ── Cluster D slice 2 (sprint-4/05) — public cart + holds + checkout ─────────

from datetime import timedelta  # noqa: E402

HOLD_TTL_MINUTES = 8


class CartService:
    """Anonymous cart + DB-locked capacity holds + confirm. RESERVED seats hold
    via row lock (free→held); GA via a counter + ``capacity_holds``. Holds expire
    (TTL) and are swept lazily on read/confirm. Confirm pairs the held units with
    the supplied attendees and delegates to ``CheckoutService.confirm`` (atomic
    ems→finance). Public flow: tenant resolved from the slug in the path."""

    def __init__(self, db: Session):
        self.db = db

    # ── helpers ──
    def _offering(self, tenant_id, project_id, offering_id) -> ProjectProduct:
        return OfferingService(self.db).get(tenant_id, project_id, offering_id)

    def _ga_remaining(self, tenant_id, offering: ProjectProduct) -> int:
        # void/refunded tickets release the GA counter (AC-05-TKT-04) — they no
        # longer occupy capacity, so they're excluded from the sold count.
        sold = (
            self.db.query(Ticket)
            .filter(
                Ticket.tenant_id == tenant_id,
                Ticket.project_product_id == offering.id,
                Ticket.status.notin_(("void", "refunded")),
            )
            .count()
        )
        held_qty = (
            self.db.query(func.coalesce(func.sum(CapacityHold.qty), 0))
            .filter(
                CapacityHold.tenant_id == tenant_id,
                CapacityHold.project_product_id == offering.id,
                CapacityHold.expires_at > _now(),
            )
            .scalar()
        ) or 0
        return max(int(offering.capacity) - sold - int(held_qty), 0)

    def _sweep(self, tenant_id) -> None:
        """Release expired holds (RESERVED units + GA rows)."""
        now = _now()
        self.db.query(CapacityUnit).filter(
            CapacityUnit.tenant_id == tenant_id,
            CapacityUnit.status == "held",
            CapacityUnit.held_until.isnot(None),
            CapacityUnit.held_until < now,
        ).update({"status": "free", "held_until": None, "held_by_cart_id": None}, synchronize_session=False)
        self.db.query(CapacityHold).filter(
            CapacityHold.tenant_id == tenant_id, CapacityHold.expires_at < now
        ).delete(synchronize_session=False)
        self.db.flush()

    def _touch(self, cart: Cart) -> None:
        cart.expires_at = _now() + timedelta(minutes=HOLD_TTL_MINUTES)

    # ── checkout catalogue ──
    def checkout(self, tenant_id, project_id) -> dict:
        project = ProjectService(self.db).get(tenant_id, project_id)
        offs = OfferingService(self.db).list(tenant_id, project_id)
        out = []
        for o in offs:
            reserved = o.allocation_mode == "RESERVED"
            remaining = (
                self.db.query(CapacityUnit)
                .filter(CapacityUnit.project_product_id == o.id, CapacityUnit.status == "free")
                .count()
                if reserved
                else self._ga_remaining(tenant_id, o)
            )
            out.append(
                {
                    "id": o.id,
                    "productName": _product_name(self.db, tenant_id, o.product_id),
                    "allocationMode": o.allocation_mode,
                    "price": o.price or 0,
                    "currency": o.currency,
                    "taxRate": o.tax_rate or 0,
                    "remaining": remaining,
                    "hasSeatMap": reserved,
                }
            )
        return {"title": project.title, "currency": (offs[0].currency if offs else "USD"), "offerings": out}

    def create_cart(self, tenant_id, project_id) -> Cart:
        ProjectService(self.db).get(tenant_id, project_id)
        cart = Cart(tenant_id=tenant_id, project_id=project_id, session_token=str(uuid.uuid4()), status="open")
        self.db.add(cart)
        self.db.commit()
        self.db.refresh(cart)
        return cart

    def _get_cart(self, tenant_id, cart_id) -> Cart:
        c = self.db.query(Cart).filter(Cart.id == cart_id, Cart.tenant_id == tenant_id).first()
        if c is None:
            raise HTTPException(404, "Cart not found.")
        return c

    # ── holds ──
    def hold_seat(self, tenant_id, cart_id, offering_id, seat_unit_id) -> dict:
        cart = self._get_cart(tenant_id, cart_id)
        self._sweep(tenant_id)
        q = self.db.query(CapacityUnit).filter(
            CapacityUnit.id == seat_unit_id,
            CapacityUnit.tenant_id == tenant_id,
            CapacityUnit.project_product_id == offering_id,
        )
        try:
            q = q.with_for_update()  # Postgres row lock; SQLite no-op
        except Exception:  # noqa: BLE001
            pass
        unit = q.first()
        if unit is None:
            raise HTTPException(404, "Seat not found.")
        if unit.status == "free":
            unit.status = "held"
            unit.held_by_cart_id = cart.id
            unit.held_until = _now() + timedelta(minutes=HOLD_TTL_MINUTES)
        elif unit.status == "held" and unit.held_by_cart_id == cart.id:
            unit.status = "free"
            unit.held_by_cart_id = None
            unit.held_until = None
        else:
            raise HTTPException(409, "Seat is no longer available.")
        self._touch(cart)
        self.db.commit()
        return self._cart_payload(tenant_id, cart)

    def set_ga(self, tenant_id, cart_id, offering_id, qty: int) -> dict:
        cart = self._get_cart(tenant_id, cart_id)
        self._sweep(tenant_id)
        offering = self._offering(tenant_id, cart.project_id, offering_id)
        existing = (
            self.db.query(CapacityHold)
            .filter(CapacityHold.cart_id == cart.id, CapacityHold.project_product_id == offering_id)
            .first()
        )
        qty = max(0, int(qty))
        # remaining excluding this cart's current hold
        current = existing.qty if existing else 0
        if qty > self._ga_remaining(tenant_id, offering) + current:
            raise HTTPException(409, "Not enough capacity remaining.")
        if qty == 0:
            if existing:
                self.db.delete(existing)
        elif existing:
            existing.qty = qty
            existing.expires_at = _now() + timedelta(minutes=HOLD_TTL_MINUTES)
        else:
            self.db.add(
                CapacityHold(
                    tenant_id=tenant_id,
                    project_product_id=offering_id,
                    cart_id=cart.id,
                    qty=qty,
                    expires_at=_now() + timedelta(minutes=HOLD_TTL_MINUTES),
                )
            )
        self._touch(cart)
        self.db.commit()
        return self._cart_payload(tenant_id, cart)

    def get_cart(self, tenant_id, cart_id) -> dict:
        cart = self._get_cart(tenant_id, cart_id)
        self._sweep(tenant_id)
        self.db.commit()
        return self._cart_payload(tenant_id, cart)

    def seatmap(self, tenant_id, project_id, offering_id, cart_id) -> list:
        self._offering(tenant_id, project_id, offering_id)
        self._sweep(tenant_id)
        self.db.commit()
        units = (
            self.db.query(CapacityUnit)
            .filter(CapacityUnit.project_product_id == offering_id, CapacityUnit.tenant_id == tenant_id)
            .order_by(CapacityUnit.y.asc(), CapacityUnit.x.asc())
            .all()
        )
        rows: dict = {}
        for u in units:
            key = u.row or str(u.y)
            mine = u.held_by_cart_id == cart_id
            rows.setdefault(key, []).append(
                {
                    "id": u.id,
                    "label": u.label,
                    "row": u.row or key,
                    "number": u.number or "",
                    "zone": u.zone,
                    "status": u.status,
                    "mine": mine,
                }
            )
        return [{"row": k, "seats": v} for k, v in rows.items()]

    # ── payload ──
    def _cart_payload(self, tenant_id, cart: Cart) -> dict:
        lines = []
        subtotal = 0.0
        tax = 0.0
        # RESERVED held seats grouped by offering
        held_units = (
            self.db.query(CapacityUnit)
            .filter(CapacityUnit.tenant_id == tenant_id, CapacityUnit.held_by_cart_id == cart.id, CapacityUnit.status == "held")
            .all()
        )
        by_off: dict = {}
        for u in held_units:
            by_off.setdefault(u.project_product_id, []).append(u)
        for off_id, units in by_off.items():
            o = self.db.query(ProjectProduct).filter(ProjectProduct.id == off_id, ProjectProduct.tenant_id == tenant_id).first()
            if not o:
                continue
            price = o.price or 0
            amount = price * len(units)
            subtotal += amount
            tax += amount * (o.tax_rate or 0) / 100
            lines.append(
                {
                    "offeringId": off_id,
                    "productName": _product_name(self.db, tenant_id, o.product_id),
                    "allocationMode": "RESERVED",
                    "unitPrice": price,
                    "currency": o.currency,
                    "qty": len(units),
                    "seatIds": [u.id for u in units],
                    "seatLabels": [u.label for u in units],
                }
            )
        # GA holds
        ga_holds = self.db.query(CapacityHold).filter(CapacityHold.cart_id == cart.id, CapacityHold.expires_at > _now()).all()
        for h in ga_holds:
            o = self.db.query(ProjectProduct).filter(ProjectProduct.id == h.project_product_id, ProjectProduct.tenant_id == tenant_id).first()
            if not o or h.qty <= 0:
                continue
            price = o.price or 0
            amount = price * h.qty
            subtotal += amount
            tax += amount * (o.tax_rate or 0) / 100
            lines.append(
                {
                    "offeringId": h.project_product_id,
                    "productName": _product_name(self.db, tenant_id, o.product_id),
                    "allocationMode": "GA",
                    "unitPrice": price,
                    "currency": o.currency,
                    "qty": h.qty,
                    "seatIds": [],
                    "seatLabels": [],
                }
            )
        currency = lines[0]["currency"] if lines else "USD"
        has_holds = bool(lines)
        return {
            "id": cart.id,
            "lines": lines,
            "subtotal": round(subtotal, 2),
            "tax": round(tax, 2),
            "total": round(subtotal + tax, 2),
            "currency": currency,
            "expiresAt": cart.expires_at.isoformat() if (has_holds and cart.expires_at) else None,
        }

    # ── confirm ──
    def confirm(self, tenant_id, cart_id, attendees: list) -> dict:
        cart = self._get_cart(tenant_id, cart_id)
        self._sweep(tenant_id)
        if cart.status != "open":
            raise HTTPException(409, "This cart has already been confirmed.")
        # build the ordered ticket slots from holds
        slots = []
        held_units = (
            self.db.query(CapacityUnit)
            .filter(CapacityUnit.tenant_id == tenant_id, CapacityUnit.held_by_cart_id == cart.id, CapacityUnit.status == "held")
            .all()
        )
        for u in held_units:
            slots.append({"offeringId": u.project_product_id, "capacityUnitId": u.id})
        ga_holds = self.db.query(CapacityHold).filter(CapacityHold.cart_id == cart.id, CapacityHold.expires_at > _now()).all()
        for h in ga_holds:
            for _ in range(h.qty):
                slots.append({"offeringId": h.project_product_id, "capacityUnitId": None})
        if not slots:
            raise HTTPException(422, "Your cart is empty or the hold expired.")
        if len(attendees) < len(slots):
            raise HTTPException(422, "Provide an attendee for every ticket.")
        items = [{**slot, "attendee": attendees[i]} for i, slot in enumerate(slots)]
        order = CheckoutService(self.db).confirm(tenant_id, cart.project_id, items)
        # converted; clear GA holds (RESERVED units already flipped to sold by confirm)
        self.db.query(CapacityHold).filter(CapacityHold.cart_id == cart.id).delete(synchronize_session=False)
        cart.status = "converted"
        cart.expires_at = None
        self.db.commit()
        return order


# ── Cluster D slice 3 (sprint-4/05) — tickets · nomination · scan · check-in ──

from cryptography.fernet import InvalidToken  # noqa: E402

from app.secrets import decrypt_secret  # noqa: E402


def _status_id_by_key(db: Session, entity_type: str, tenant_id: str, key: str) -> Optional[str]:
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id.is_(None),
            Status.key == key,
        )
        .first()
    )
    return row.id if row else None


class TicketService:
    """Ticket lifecycle on the status engine + signed-QR nomination/transfer.

    The legacy ``Ticket.status`` string is kept in sync with ``status_id`` so the
    derived check-in aggregate facts (which filter the string mirror) stay
    correct. Every ticket status change emits a TICKET_ENTITY event so the
    cross-entity DerivedTrigger re-derives the owning participant's Checked-in."""

    def __init__(self, db: Session):
        self.db = db

    def _get(self, tenant_id, ticket_id) -> Ticket:
        t = (
            self.db.query(Ticket)
            .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
            .first()
        )
        if t is None:
            raise HTTPException(404, "Ticket not found.")
        return t

    def list_for_participant(self, tenant_id, project_id, participant_id) -> list:
        """A participant's tickets (no full tickets list yet — BL-120). Tenant-
        and project-scoped; backs the participant-detail nomination action."""
        return (
            self.db.query(Ticket)
            .filter(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.participant_id == participant_id,
            )
            .order_by(Ticket.created_at.asc())
            .all()
        )

    def list_for_project(
        self, tenant_id, project_id, *, page=0, page_size=25, search=None
    ) -> Tuple[list, int]:
        """Event-wide tickets list (BL-120) — backs the admin Tickets tab.
        Tenant- and project-scoped, paginated. Attendee/offering/seat/invoice
        details are batched (no N+1): one query per related set, one cross-module
        ``invoice.resolve`` call per distinct invoice. ``paid`` is derived from the
        resolved invoice status (comp/no-invoice = paid/NA); the cross-module
        invoice read goes through the finance capability (BL-030 soft-ref), never
        a cross-schema join."""
        from app.module_platform import resolve_capability
        from app.models.catalog import Product

        base = self.db.query(Ticket).filter(
            Ticket.tenant_id == tenant_id, Ticket.project_id == project_id
        )

        # search on attendee name/email — resolve matching profile ids first so the
        # filter stays a single batched id-set (no per-row join explosion).
        if search:
            term = f"%{search.strip()}%"
            prof_ids = [
                r[0]
                for r in self.db.query(Profile.id)
                .filter(
                    Profile.tenant_id == tenant_id,
                    func.lower(Profile.full_name).ilike(func.lower(term))
                    | func.lower(Profile.email).ilike(func.lower(term)),
                )
                .all()
            ]
            base = base.filter(Ticket.attendee_profile_id.in_(prof_ids or [""]))

        total = base.count()
        tickets = (
            base.order_by(Ticket.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        if not tickets:
            return [], total

        # ── batch the related sets (tenant-scoped) ──
        profile_ids = {t.attendee_profile_id for t in tickets if t.attendee_profile_id}
        offering_ids = {t.project_product_id for t in tickets if t.project_product_id}
        unit_ids = {t.capacity_unit_id for t in tickets if t.capacity_unit_id}
        invoice_ids = {t.invoice_id for t in tickets if t.invoice_id}
        status_ids = {t.status_id for t in tickets if t.status_id}

        profiles = {
            p.id: p
            for p in self.db.query(Profile)
            .filter(Profile.tenant_id == tenant_id, Profile.id.in_(profile_ids or [""]))
            .all()
        }
        offerings = {
            o.id: o
            for o in self.db.query(ProjectProduct)
            .filter(
                ProjectProduct.tenant_id == tenant_id,
                ProjectProduct.id.in_(offering_ids or [""]),
            )
            .all()
        }
        product_ids = {o.product_id for o in offerings.values() if o.product_id}
        product_names = {
            p.id: p.name
            for p in self.db.query(Product)
            .filter(Product.tenant_id == tenant_id, Product.id.in_(product_ids or [""]))
            .all()
        }
        units = {
            u.id: u
            for u in self.db.query(CapacityUnit)
            .filter(
                CapacityUnit.tenant_id == tenant_id,
                CapacityUnit.id.in_(unit_ids or [""]),
            )
            .all()
        }
        statuses = {
            s.id: s
            for s in self.db.query(Status)
            .filter(Status.id.in_(status_ids or [""]))
            .all()
        }

        # cross-module invoice read via the capability (BL-030 soft-ref). Resolve
        # each distinct invoice once; missing provider/capability → all unresolved
        # (paid stays False), never an exception.
        invoices: dict = {}
        if invoice_ids:
            resolver = resolve_capability(self.db, tenant_id, "invoice.resolve", 1)
            if resolver is not None:
                for inv_id in invoice_ids:
                    inv = resolver(self.db, tenant_id, {"id": inv_id})
                    if inv is not None:
                        invoices[inv_id] = inv

        rows = []
        for t in tickets:
            prof = profiles.get(t.attendee_profile_id)
            offering = offerings.get(t.project_product_id)
            offering_name = (
                product_names.get(offering.product_id, "") if offering else ""
            )
            unit = units.get(t.capacity_unit_id)
            st = statuses.get(t.status_id)
            inv = invoices.get(t.invoice_id) if t.invoice_id else None
            inv_status_key = None
            if inv is not None and inv.get("statusId"):
                inv_st = statuses.get(inv["statusId"]) or (
                    self.db.query(Status).filter(Status.id == inv["statusId"]).first()
                )
                if inv_st is not None:
                    statuses[inv_st.id] = inv_st  # cache for the next ticket
                    inv_status_key = inv_st.key
            # comp (no invoice) = paid/NA; otherwise paid iff the invoice status is paid.
            paid = t.invoice_id is None or inv_status_key == "paid"
            rows.append(
                {
                    "id": t.id,
                    "attendeeName": (prof.full_name if prof else None) or "",
                    "attendeeEmail": (prof.email if prof else None) or "",
                    "offeringName": offering_name,
                    "seatLabel": unit.label if unit else None,
                    "ticketStatus": st.label if st else (t.status or ""),
                    "ticketStatusKey": st.key if st else (t.status or ""),
                    "paid": paid,
                    "invoiceId": t.invoice_id,
                    "invoiceTotal": inv.get("total") if inv else None,
                    "currency": inv.get("currency") if inv else None,
                    "qrToken": t.qr_token,
                    "registeredAt": t.created_at,
                }
            )
        return rows, total

    def _move_to_key(self, tenant_id, ticket: Ticket, key: str, actor, commit: bool = True) -> None:
        """Drive the ticket through the ONE status_machine to the status keyed
        ``key`` (Issued→Valid→…); mirror the legacy string; emit the event.

        ``commit=False`` (Cluster F slice 4 — refund called inside the finance
        refund transaction) leaves the commit + the after-commit participant
        re-derive to the caller's transaction; the caller MUST emit the
        status_changed event after its own commit so eligibility re-derives."""
        from app.workflow_engine.entity_events import notify_entity_event

        to_id = _status_id_by_key(self.db, TICKET_ENTITY, tenant_id, key)
        if to_id is None:
            raise HTTPException(409, "The ticket status graph is not seeded.")
        status_machine.transition(
            self.db, TICKET_ENTITY, ticket, to_id, actor, tenant_id=tenant_id, commit=False
        )
        ticket.status = key  # keep the aggregate-facing mirror in sync
        if not commit:
            self.db.flush()
            return
        self.db.commit()
        self.db.refresh(ticket)
        # Re-derive the owning participant (sprint-4/03 R3-2) — failure-isolated.
        notify_entity_event(
            self.db, TICKET_ENTITY, "status_changed", ticket, tenant_id=tenant_id, actor=actor
        )

    def nominate(self, tenant_id, ticket_id, new_profile_id, actor) -> dict:
        """Reassign a ticket to a new attendee Profile. Status → Transferred,
        QR rotated (old token dies via the nonce change). The nominee can't
        re-transfer (a Transferred ticket refuses another transfer). Money
        untouched (invoice_id unchanged). Re-links the participant on the target
        project, copying the offering's grants (segment/role)."""
        ticket = self._get(tenant_id, ticket_id)
        if ticket.status in ("transferred", "void", "refunded"):
            raise HTTPException(
                409, "This ticket can no longer be transferred."
            )
        # validate the target profile (tenant-scoped, not blocked)
        profile = (
            self.db.query(Profile)
            .filter(
                Profile.id == new_profile_id,
                Profile.tenant_id == tenant_id,
                Profile.is_deleted.is_(False),
            )
            .first()
        )
        if profile is None:
            raise HTTPException(422, "Nominee profile not found.")
        if profile.status_id:
            st = self.db.query(Status).filter(Status.id == profile.status_id).first()
            if st is not None and st.blocks_access:
                raise HTTPException(422, "The nominee is suspended and can't hold a ticket.")
        offering = OfferingService(self.db).get(tenant_id, ticket.project_id, ticket.project_product_id)
        participant = CheckoutService(self.db)._get_or_create_participant(
            tenant_id, ticket.project_id, profile, offering
        )
        # rotate QR (new nonce → the previously-issued ciphertext no longer matches)
        ticket.attendee_profile_id = profile.id
        ticket.participant_id = participant.id
        ticket.qr_nonce = uuid.uuid4().hex
        ticket.qr_token = encrypt_secret({"t": ticket.id, "n": ticket.qr_nonce})
        if ticket.capacity_unit_id:
            unit = (
                self.db.query(CapacityUnit)
                .filter(CapacityUnit.id == ticket.capacity_unit_id, CapacityUnit.tenant_id == tenant_id)
                .first()
            )
            if unit is not None:
                unit.participant_id = participant.id
        self.db.flush()
        # Transferred is terminal on the ticket graph (a fresh ticket isn't
        # minted for the nominee in v1 — the SAME ticket changes hands).
        self._move_to_key(tenant_id, ticket, "transferred", actor)
        return {
            "ticketId": ticket.id,
            "attendeeProfileId": ticket.attendee_profile_id,
            "participantId": ticket.participant_id,
            "status": ticket.status,
            "qrRotated": True,
        }

    def void(self, tenant_id, ticket_id, actor) -> dict:
        """Void a ticket (AC-05-TKT-04): status → Void, QR rotated (old token
        dies at scan), RESERVED seat released to ``free`` (GA frees via the
        sold-count exclusion). Money/invoice_id untouched (reversal = Cluster F)."""
        return self._void_or_refund(tenant_id, ticket_id, "void", actor)

    def refund(self, tenant_id, ticket_id, actor, commit: bool = True) -> dict:
        """Refund a ticket (AC-05-TKT-04 / Cluster F slice 4 AC-07-41/42): status
        → Refunded, QR rotated dead, seat released. ``commit=False`` is used when
        the finance refund flow drives this inside its own transaction (the money
        + ticket move must commit atomically); the caller then emits the
        status_changed event so participant eligibility re-derives (AC-07-44)."""
        return self._void_or_refund(tenant_id, ticket_id, "refunded", actor, commit=commit)

    def _void_or_refund(self, tenant_id, ticket_id, key: str, actor, commit: bool = True) -> dict:
        ticket = self._get(tenant_id, ticket_id)
        verb = "voided" if key == "void" else "refunded"
        if ticket.status in ("void", "refunded", "transferred"):
            raise HTTPException(409, f"This ticket can no longer be {verb}.")
        # rotate the QR (new nonce → the previously-issued ciphertext dies at scan)
        ticket.qr_nonce = uuid.uuid4().hex
        ticket.qr_token = encrypt_secret({"t": ticket.id, "n": ticket.qr_nonce})
        # release the RESERVED seat back to the pool (GA has no unit; its counter
        # frees via the void/refunded exclusion in _ga_remaining + soldCount).
        if ticket.capacity_unit_id:
            unit = (
                self.db.query(CapacityUnit)
                .filter(
                    CapacityUnit.id == ticket.capacity_unit_id,
                    CapacityUnit.tenant_id == tenant_id,
                )
                .first()
            )
            if unit is not None:
                unit.status = "free"
                unit.participant_id = None
                unit.held_until = None
                unit.held_by_cart_id = None
        self.db.flush()
        # fire the status transition (strict graph — a missing edge for the
        # current state is a clean 409, never a 500).
        from app.services.status_machine import StatusMachineError

        try:
            self._move_to_key(tenant_id, ticket, key, actor, commit=commit)
        except StatusMachineError as exc:
            if commit:
                self.db.rollback()
            raise HTTPException(409, exc.message) from exc
        return {
            "ticketId": ticket.id,
            "status": ticket.status,
            "qrRotated": True,
            "seatReleased": ticket.capacity_unit_id is not None,
        }

    def scan(self, tenant_id, checkpoint_id, qr_token: str, actor) -> dict:
        """Validate a signed QR at a checkpoint, run access checks, write a
        checkpoint_log, and (on first admit) move the ticket → CheckedIn (which
        re-derives the participant's Checked-in). Tampered/invalid token = a
        clean rejection (never a 500). A re-scan of an already-admitted ticket =
        an 'already_in' result via the dedup, not a 500. Slice 3 checkpoints are
        single-entry only (multi = Cluster H)."""
        checkpoint = CheckpointService(self.db)._get(tenant_id, checkpoint_id)

        # 1) decode + signature check — fail closed on ANY error (tamper, garbage,
        # decode/type errors). A bad token is a clean rejection, never a 500.
        try:
            payload = decrypt_secret(qr_token)
        except Exception:  # noqa: BLE001 — fail closed: any decode failure = rejection
            return {"result": "denied", "reason": "Invalid or tampered ticket."}
        ticket_id = payload.get("t") if isinstance(payload, dict) else None
        nonce = payload.get("n") if isinstance(payload, dict) else None
        if not ticket_id:
            return {"result": "denied", "reason": "Invalid ticket."}

        ticket = (
            self.db.query(Ticket)
            .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
            .first()
        )
        if ticket is None:
            return {"result": "denied", "reason": "Ticket not found."}
        # 2) nonce check — a rotated (transferred/void/refund) QR is dead
        if ticket.qr_nonce and nonce != ticket.qr_nonce:
            return {"result": "denied", "reason": "This ticket code has been superseded."}
        # 3) checkpoint must belong to the ticket's event
        if checkpoint.project_id != ticket.project_id:
            return self._log_denied(tenant_id, checkpoint, ticket, "Ticket is for a different event.")
        # 4) ticket state — void/refunded/transferred can't enter
        if ticket.status in ("void", "refunded", "transferred"):
            return self._log_denied(tenant_id, checkpoint, ticket, f"Ticket is {ticket.status}.")
        # 5) segment gating (if the checkpoint gates a segment) — tenant-scoped
        if checkpoint.segment_id:
            participant = None
            if ticket.participant_id:
                participant = (
                    self.db.query(ProjectParticipant)
                    .filter(
                        ProjectParticipant.id == ticket.participant_id,
                        ProjectParticipant.tenant_id == tenant_id,
                    )
                    .first()
                )
            if participant is None or participant.segment_id != checkpoint.segment_id:
                return self._log_denied(tenant_id, checkpoint, ticket, "Ticket not valid for this access area.")

        # 6) dedup — a prior admit at this single-entry checkpoint returns already_in
        prior = (
            self.db.query(CheckpointLog)
            .filter(
                CheckpointLog.checkpoint_id == checkpoint.id,
                CheckpointLog.ticket_id == ticket.id,
                CheckpointLog.result == "admitted",
            )
            .first()
        )
        if prior is not None:
            return {
                "result": "already_in",
                "reason": "Already checked in at this checkpoint.",
                "ticketId": ticket.id,
                "scannedAt": prior.scanned_at,
            }

        # 7) admit — log + (first admit) move the ticket to CheckedIn
        log = CheckpointLog(
            tenant_id=tenant_id,
            checkpoint_id=checkpoint.id,
            ticket_id=ticket.id,
            participant_id=ticket.participant_id,
            result="admitted",
        )
        self.db.add(log)
        try:
            self.db.flush()
        except Exception:  # noqa: BLE001 — UNIQUE backstop race (multi reader) = already in
            self.db.rollback()
            return {"result": "already_in", "reason": "Already checked in.", "ticketId": ticket.id}
        if ticket.status != "checked_in":
            self._move_to_key(tenant_id, ticket, "checked_in", actor)
        else:
            self.db.commit()
        return {
            "result": "admitted",
            "ticketId": ticket.id,
            "participantId": ticket.participant_id,
            "scannedAt": log.scanned_at,
        }

    def _log_denied(self, tenant_id, checkpoint, ticket, reason) -> dict:
        log = CheckpointLog(
            tenant_id=tenant_id,
            checkpoint_id=checkpoint.id,
            ticket_id=ticket.id,
            participant_id=ticket.participant_id,
            result="denied",
            reason=reason,
        )
        self.db.add(log)
        try:
            self.db.commit()
        except Exception:  # noqa: BLE001 — a repeat denial hits the dedup; ignore
            self.db.rollback()
        return {"result": "denied", "reason": reason, "ticketId": ticket.id}


class CheckpointService:
    def __init__(self, db: Session):
        self.db = db

    def _get(self, tenant_id, checkpoint_id) -> Checkpoint:
        c = (
            self.db.query(Checkpoint)
            .filter(
                Checkpoint.id == checkpoint_id,
                Checkpoint.tenant_id == tenant_id,
                Checkpoint.is_deleted.is_(False),
            )
            .first()
        )
        if c is None:
            raise HTTPException(404, "Checkpoint not found.")
        return c

    def list(self, tenant_id, project_id) -> list:
        ProjectService(self.db).get(tenant_id, project_id)  # tenant + existence guard
        return (
            self.db.query(Checkpoint)
            .filter(
                Checkpoint.tenant_id == tenant_id,
                Checkpoint.project_id == project_id,
                Checkpoint.is_deleted.is_(False),
            )
            .order_by(Checkpoint.created_at.asc())
            .all()
        )

    def create(self, tenant_id, project_id, data) -> Checkpoint:
        ProjectService(self.db).get(tenant_id, project_id)
        c = Checkpoint(
            tenant_id=tenant_id,
            project_id=project_id,
            name=data["name"],
            segment_id=data.get("segmentId"),
            entry_type=data.get("entryType", "single"),
        )
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def list_logs(self, tenant_id, project_id, checkpoint_id, *, page=0, page_size=25) -> tuple[list[dict], int]:
        """Recent scans for a checkpoint, newest-first, with the attendee name
        resolved (ticket → attendee profile, batch — no N+1). Tenant + project +
        checkpoint scoped."""
        self._get(tenant_id, checkpoint_id)  # tenant + existence guard (404 otherwise)
        base = (
            self.db.query(CheckpointLog)
            .filter(
                CheckpointLog.tenant_id == tenant_id,
                CheckpointLog.checkpoint_id == checkpoint_id,
            )
        )
        total = base.count()
        logs = (
            base.order_by(CheckpointLog.scanned_at.desc(), CheckpointLog.id.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        # batch-resolve attendee names: ticket → attendee_profile_id (fallback
        # participant.profile_id), then one profiles query for the set.
        ticket_ids = {log.ticket_id for log in logs if log.ticket_id}
        tickets = {
            t.id: t
            for t in self.db.query(Ticket)
            .filter(Ticket.id.in_(ticket_ids), Ticket.tenant_id == tenant_id)
            .all()
        } if ticket_ids else {}
        participant_ids = {
            t.participant_id
            for t in tickets.values()
            if t.attendee_profile_id is None and t.participant_id
        }
        participants = {
            p.id: p
            for p in self.db.query(ProjectParticipant)
            .filter(
                ProjectParticipant.id.in_(participant_ids),
                ProjectParticipant.tenant_id == tenant_id,
            )
            .all()
        } if participant_ids else {}
        profile_ids: set = set()
        for t in tickets.values():
            if t.attendee_profile_id:
                profile_ids.add(t.attendee_profile_id)
            elif t.participant_id and t.participant_id in participants:
                profile_ids.add(participants[t.participant_id].profile_id)
        profiles = {
            p.id: p
            for p in self.db.query(Profile)
            .filter(Profile.id.in_(profile_ids), Profile.tenant_id == tenant_id)
            .all()
        } if profile_ids else {}

        def _name(ticket) -> Optional[str]:
            if ticket is None:
                return None
            pid = ticket.attendee_profile_id
            if pid is None and ticket.participant_id in participants:
                pid = participants[ticket.participant_id].profile_id
            prof = profiles.get(pid) if pid else None
            if prof is None:
                return None
            return prof.full_name or prof.email

        rows = [
            {
                "id": log.id,
                "checkpointId": log.checkpoint_id,
                "ticketId": log.ticket_id,
                "attendeeName": _name(tickets.get(log.ticket_id)),
                "result": log.result,
                "reason": log.reason,
                "scannedAt": log.scanned_at,
            }
            for log in logs
        ]
        return rows, total


# ── EMS event review configuration (sprint-4/06 Part B, AC-06-49/50) ──────────


class EventReviewConfigService:
    """EMS's *configuration* of the generic CORE review engine (AC-06-49). Builds
    a ``review_configuration`` whose roles bind to EMS PERSONAS:

    - Author  (can_submit, source PERSONA → the *participant* persona) — AC-06-50
      (submitting auto-derives the participant persona; this lets a participant
      submit);
    - Reviewer(can_review, source PERSONA → the *reviewer* persona) — pool resolves
      via the EMS PERSONA actor-pool resolver (AC-06-10/51);
    - Decision-maker (can_decide, source PERSONA → the *decision_maker* persona, or
      EXPLICIT named profiles when provided).

    The generic engine + the seeded allocate workflow (ReviewConfigService) do the
    rest. The staff UI to drive this is slice-1 frontend; here = the service helper
    + the persona binding so the canonical event flow is configurable end to end.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_event_review_config(
        self,
        tenant_id: str,
        *,
        project_id: str,
        submission_form_id: str,
        review_form_id: str,
        score_field_key: Optional[str] = None,
        required_review_count: int = 1,
        review_start_status_id: Optional[str] = None,
        revisions_status_id: Optional[str] = None,
        accepted_status_id: Optional[str] = None,
        rejected_status_id: Optional[str] = None,
        window_start=None,
        window_end=None,
        name: Optional[str] = None,
        decision_maker_actor_ids: Optional[List[str]] = None,
    ):
        """Create the persona-bound review configuration for an event. Returns the
        core ``ReviewConfiguration``. ``project_id`` validates the event exists +
        names the config; the persona-bound roles resolve their pools per-event via
        the EMS resolver. ``decision_maker_actor_ids`` (profile ids) switches the
        decision role to EXPLICIT named profiles instead of the persona pool."""
        from app.review_engine.service import ReviewConfigService
        from modules.ems.persona_repository import PersonaRepository

        project = ProjectService(self.db).get(tenant_id, project_id)
        persona_repo = PersonaRepository(self.db)

        def _persona_id(key: str) -> str:
            persona = persona_repo.get_persona_by_key(tenant_id, key)
            if persona is None:
                raise HTTPException(
                    422, f"The '{key}' persona is not seeded for this tenant."
                )
            return persona.id

        roles: List[dict] = [
            {
                "key": "author",
                "label": "Author",
                "can_submit": True,
                "actor_source": "PERSONA",
                "actor_identity_kind": "profile",
                "bound_persona_id": _persona_id("participant"),
                "sort_order": 0,
            },
            {
                "key": "reviewer",
                "label": "Reviewer",
                "can_review": True,
                "actor_source": "PERSONA",
                "actor_identity_kind": "profile",
                "bound_persona_id": _persona_id("reviewer"),
                "sort_order": 1,
            },
        ]
        if decision_maker_actor_ids:
            roles.append(
                {
                    "key": "decision_maker",
                    "label": "Decision Maker",
                    "can_decide": True,
                    "actor_source": "EXPLICIT",
                    "actor_identity_kind": "profile",
                    "actors": [
                        {"actor_kind": "profile", "actor_id": pid, "sort_order": i}
                        for i, pid in enumerate(decision_maker_actor_ids)
                    ],
                    "sort_order": 2,
                }
            )
        else:
            roles.append(
                {
                    "key": "decision_maker",
                    "label": "Decision Maker",
                    "can_decide": True,
                    "actor_source": "PERSONA",
                    "actor_identity_kind": "profile",
                    "bound_persona_id": _persona_id("decision_maker"),
                    "sort_order": 2,
                }
            )

        try:
            return ReviewConfigService(self.db).create_config(
                tenant_id,
                name=name or f"Reviews — {project.title}",
                form_id=submission_form_id,
                review_form_id=review_form_id,
                # Bind the config to the event (AC-06-25/24/49) so every review
                # surface can narrow to it via the global event-filter pill.
                context_type="project",
                context_id=project_id,
                score_field_key=score_field_key,
                required_review_count=required_review_count,
                review_start_status_id=review_start_status_id,
                revisions_status_id=revisions_status_id,
                accepted_status_id=accepted_status_id,
                rejected_status_id=rejected_status_id,
                window_start=window_start,
                window_end=window_end,
                roles=roles,
            )
        except Exception as exc:  # surface the engine's validation as HTTP 422
            from app.review_engine.service import ReviewValidationError

            if isinstance(exc, ReviewValidationError):
                raise HTTPException(422, str(exc))
            raise

"""CRM importer configs (sprint-4/08) — client + lead (moved from EMS). Product
import lives in core now (app/catalog/importers.py)."""
import re
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.import_engine.registry import ImportColumn, ImporterDef, register_importer
from modules.crm.models import Client, Lead

CLIENT_IMPORT_KEY = "client"
LEAD_IMPORT_KEY = "lead"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(v):
    return "not a valid email address" if v and not _EMAIL_RE.match(str(v)) else None


def _initial_status_id(db: Session, entity_type: str, tenant_id: str):
    from app.models.status import Status

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


# ── client ───────────────────────────────────────────────────────────────────


def _client_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    return {r[0] for r in db.query(Client.id).filter(Client.tenant_id == tenant_id, Client.id.in_(ids)).all()}


_CLIENT_FIELDS = {
    "name": "name",
    "registrationNo": "registration_no",
    "contactPerson": "contact_person",
    "contactEmail": "contact_email",
    "contactPhone": "contact_phone",
}


def _create_clients(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    now = datetime.now(timezone.utc)
    status_id = _initial_status_id(db, "client", tenant_id)
    ids, mappings = [], []
    for r in rows:
        cid = str(uuid.uuid4())
        ids.append(cid)
        m = {"id": cid, "tenant_id": tenant_id, "status_id": status_id, "is_deleted": False, "created_at": now, "updated_at": now}
        for key, attr in _CLIENT_FIELDS.items():
            m[attr] = r.get(key)
        mappings.append(m)
    if mappings:
        db.bulk_insert_mappings(Client, mappings)
    return ids


def _update_clients(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    ids = []
    for r in rows:
        patch = {attr: r[key] for key, attr in _CLIENT_FIELDS.items() if r.get(key) is not None}
        if patch:
            db.query(Client).filter(Client.tenant_id == tenant_id, Client.id == r["id"]).update(patch, synchronize_session=False)
        ids.append(r["id"])
    return ids


# ── lead ─────────────────────────────────────────────────────────────────────


def _lead_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    return {r[0] for r in db.query(Lead.id).filter(Lead.tenant_id == tenant_id, Lead.id.in_(ids)).all()}


_LEAD_FIELDS = {
    "title": "title",
    "clientId": "client_id",
    "source": "source",
    "contactName": "contact_name",
    "contactEmail": "contact_email",
    "contactPhone": "contact_phone",
    "notes": "notes",
}


def _validate_lead_client_ids(db: Session, tenant_id: str, rows: List[dict]) -> None:
    wanted = {r.get("clientId") for r in rows if r.get("clientId")}
    if not wanted:
        return
    found = {r[0] for r in db.query(Client.id).filter(Client.tenant_id == tenant_id, Client.id.in_(list(wanted))).all()}
    missing = wanted - found
    if missing:
        raise HTTPException(422, f"These client IDs don't belong to this tenant: {', '.join(sorted(missing))}")


def _create_leads(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    _validate_lead_client_ids(db, tenant_id, rows)
    now = datetime.now(timezone.utc)
    status_id = _initial_status_id(db, "lead", tenant_id)
    ids, mappings = [], []
    for r in rows:
        lid = str(uuid.uuid4())
        ids.append(lid)
        m = {"id": lid, "tenant_id": tenant_id, "status_id": status_id, "is_deleted": False, "created_at": now, "updated_at": now}
        for key, attr in _LEAD_FIELDS.items():
            m[attr] = r.get(key)
        mappings.append(m)
    if mappings:
        db.bulk_insert_mappings(Lead, mappings)
    return ids


def _update_leads(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    _validate_lead_client_ids(db, tenant_id, rows)
    ids = []
    for r in rows:
        patch = {attr: r[key] for key, attr in _LEAD_FIELDS.items() if r.get(key) is not None}
        if patch:
            db.query(Lead).filter(Lead.tenant_id == tenant_id, Lead.id == r["id"]).update(patch, synchronize_session=False)
        ids.append(r["id"])
    return ids


def register_crm_importers() -> None:
    register_importer(
        ImporterDef(
            entity_type=CLIENT_IMPORT_KEY,
            label="Client",
            model=Client,
            columns=(
                ImportColumn(key="id", label="ID"),
                ImportColumn(key="name", label="Name", required=True),
                ImportColumn(key="registrationNo", label="Registration no."),
                ImportColumn(key="contactPerson", label="Contact person"),
                ImportColumn(key="contactEmail", label="Contact email", validators=(_valid_email,)),
                ImportColumn(key="contactPhone", label="Contact phone"),
            ),
            create_rows=_create_clients,
            update_rows=_update_clients,
            existing_ids=_client_existing_ids,
            module="crm",
            write_permission="crm_clients.manage",
        )
    )
    register_importer(
        ImporterDef(
            entity_type=LEAD_IMPORT_KEY,
            label="Lead",
            model=Lead,
            columns=(
                ImportColumn(key="id", label="ID"),
                ImportColumn(key="title", label="Title", required=True),
                ImportColumn(key="clientId", label="Client ID"),
                ImportColumn(key="source", label="Source"),
                ImportColumn(key="contactName", label="Contact name"),
                ImportColumn(key="contactEmail", label="Contact email", validators=(_valid_email,)),
                ImportColumn(key="contactPhone", label="Contact phone"),
                ImportColumn(key="notes", label="Notes"),
            ),
            create_rows=_create_leads,
            update_rows=_update_leads,
            existing_ids=_lead_existing_ids,
            module="crm",
            write_permission="crm_leads.manage",
        )
    )

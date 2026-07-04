"""CRM services (sprint-4/08) — Service-Repository, tenant-scoped. Split from EMS.

Cross-module: lead→event goes through the EMS ``project.create_from_template@1``
capability (CRM never imports EMS). Product refs validate against the CORE catalog
(``app.models.catalog.Product``). Win is a plain status move; create-event is a
separate, repeatable action.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.status import Status
from app.services import status_machine
from app.services.catalog_service import tenant_default_currency
from modules.crm.models import (
    CLIENT_ENTITY,
    LEAD_ENTITY,
    QUOTATION_ENTITY,
    SALES_ORDER_ENTITY,
    Client,
    Lead,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)


def _now():
    return datetime.now(timezone.utc)


def _iso(v):
    return v.isoformat() if v else ""


def _initial_unscoped(db: Session, entity_type: str, tenant_id: str):
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


_CLIENT_COLS = {
    "id": lambda r: r.id,
    "name": lambda r: r.name,
    "registrationNo": lambda r: r.registration_no or "",
    "contactPerson": lambda r: r.contact_person or "",
    "contactEmail": lambda r: r.contact_email or "",
    "contactPhone": lambda r: r.contact_phone or "",
    "createdAt": lambda r: _iso(r.created_at),
}
_LEAD_COLS = {
    "id": lambda r: r.id,
    "title": lambda r: r.title,
    "clientId": lambda r: r.client_id or "",
    "source": lambda r: r.source or "",
    "contactName": lambda r: r.contact_name or "",
    "contactEmail": lambda r: r.contact_email or "",
    "contactPhone": lambda r: r.contact_phone or "",
    "createdAt": lambda r: _iso(r.created_at),
}
_QUOTATION_COLS = {
    "id": lambda r: r.id,
    "clientId": lambda r: r.client_id,
    "leadId": lambda r: r.lead_id or "",
    "projectId": lambda r: r.project_id or "",
    "revisionNumber": lambda r: r.revision_number,
    "currency": lambda r: r.currency or "",
    "total": lambda r: float(sum((ln.amount or 0) for ln in r.lines)),
    "createdAt": lambda r: _iso(r.created_at),
}
_SALES_ORDER_COLS = {
    "id": lambda r: r.id,
    "docNumber": lambda r: r.doc_number or "",
    "clientId": lambda r: r.client_id,
    "quotationId": lambda r: r.quotation_id or "",
    "projectId": lambda r: r.project_id or "",
    "currency": lambda r: r.currency or "",
    "total": lambda r: float(sum((ln.amount or 0) for ln in r.lines)),
    "createdAt": lambda r: _iso(r.created_at),
}


class ClientService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"name": Client.name, "contactPerson": Client.contact_person, "createdAt": Client.created_at}

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None):
        from sqlalchemy import func, or_

        q = self.db.query(Client).filter(Client.tenant_id == tenant_id, Client.is_deleted.is_(trashed))
        if ids:
            q = q.filter(Client.id.in_(ids))
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(or_(func.lower(Client.name).like(like), func.lower(Client.contact_email).like(like)))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="asc"):
        q = self._filtered(tenant_id, search=search, trashed=trashed)
        col = self._SORT.get(sort_by, Client.created_at)
        return _paginate(q.order_by(col.asc() if sort_dir == "asc" else col.desc()), page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _CLIENT_COLS)

    def options(self, tenant_id, *, search=None, limit=20):
        q = self.db.query(Client).filter(Client.tenant_id == tenant_id, Client.is_deleted.is_(False))
        if search:
            from sqlalchemy import func

            q = q.filter(func.lower(Client.name).like(f"%{search.lower()}%"))
        return q.order_by(Client.name.asc()).limit(limit).all()

    def get(self, tenant_id, cid) -> Client:
        c = self.db.query(Client).filter(Client.id == cid, Client.tenant_id == tenant_id).first()
        if c is None:
            raise HTTPException(404, "Client not found.")
        return c

    def create(self, tenant_id, data: dict) -> Client:
        c = Client(
            tenant_id=tenant_id,
            name=data["name"],
            registration_no=data.get("registrationNo"),
            contact_person=data.get("contactPerson"),
            contact_email=data.get("contactEmail"),
            contact_phone=data.get("contactPhone"),
            status_id=_initial_unscoped(self.db, CLIENT_ENTITY, tenant_id),
        )
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def update(self, tenant_id, cid, data: dict) -> Client:
        c = self.get(tenant_id, cid)
        for key, attr in [
            ("name", "name"), ("registrationNo", "registration_no"),
            ("contactPerson", "contact_person"), ("contactEmail", "contact_email"),
            ("contactPhone", "contact_phone"),
        ]:
            if key in data and data[key] is not None:
                setattr(c, attr, data[key])
        self.db.commit()
        self.db.refresh(c)
        return c

    def delete(self, tenant_id, cid) -> None:
        c = self.get(tenant_id, cid)
        c.is_deleted = True
        c.deleted_at = _now()
        self.db.commit()

    def transition(self, tenant_id, cid, to_status_id, actor) -> Client:
        c = self.get(tenant_id, cid)
        status_machine.transition(self.db, CLIENT_ENTITY, c, to_status_id, actor, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(c)
        return c


class LeadService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"title": Lead.title, "source": Lead.source, "createdAt": Lead.created_at}

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None, client_id=None):
        from sqlalchemy import func, or_

        q = self.db.query(Lead).filter(Lead.tenant_id == tenant_id, Lead.is_deleted.is_(trashed))
        if ids:
            q = q.filter(Lead.id.in_(ids))
        if client_id:
            q = q.filter(Lead.client_id == client_id)
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(or_(func.lower(Lead.title).like(like), func.lower(Lead.contact_name).like(like)))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="desc", client_id=None):
        q = self._filtered(tenant_id, search=search, trashed=trashed, client_id=client_id)
        col = self._SORT.get(sort_by, Lead.created_at)
        return _paginate(q.order_by(col.asc() if sort_dir == "asc" else col.desc()), page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _LEAD_COLS)

    def get(self, tenant_id, lid) -> Lead:
        ld = self.db.query(Lead).filter(Lead.id == lid, Lead.tenant_id == tenant_id).first()
        if ld is None:
            raise HTTPException(404, "Lead not found.")
        return ld

    def _validate_client(self, tenant_id, client_id):
        if client_id is None:
            return
        ok = (
            self.db.query(Client.id)
            .filter(Client.id == client_id, Client.tenant_id == tenant_id, Client.is_deleted.is_(False))
            .first()
        )
        if ok is None:
            raise HTTPException(422, "Client not found.")

    def create(self, tenant_id, data: dict) -> Lead:
        self._validate_client(tenant_id, data.get("clientId"))
        ld = Lead(
            tenant_id=tenant_id,
            client_id=data.get("clientId"),
            title=data["title"],
            source=data.get("source"),
            contact_name=data.get("contactName"),
            contact_email=data.get("contactEmail"),
            contact_phone=data.get("contactPhone"),
            notes=data.get("notes"),
            status_id=_initial_unscoped(self.db, LEAD_ENTITY, tenant_id),
        )
        self.db.add(ld)
        self.db.commit()
        self.db.refresh(ld)
        return ld

    def update(self, tenant_id, lid, data: dict) -> Lead:
        ld = self.get(tenant_id, lid)
        if "clientId" in data:
            self._validate_client(tenant_id, data["clientId"])
            ld.client_id = data["clientId"]
        for key, attr in [
            ("title", "title"), ("source", "source"),
            ("contactName", "contact_name"), ("contactEmail", "contact_email"),
            ("contactPhone", "contact_phone"), ("notes", "notes"),
        ]:
            if key in data and data[key] is not None:
                setattr(ld, attr, data[key])
        self.db.commit()
        self.db.refresh(ld)
        return ld

    def delete(self, tenant_id, lid) -> None:
        ld = self.get(tenant_id, lid)
        ld.is_deleted = True
        ld.deleted_at = _now()
        self.db.commit()

    def transition(self, tenant_id, lid, to_status_id, actor) -> Lead:
        ld = self.get(tenant_id, lid)
        status_machine.transition(self.db, LEAD_ENTITY, ld, to_status_id, actor, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(ld)
        return ld

    def _is_won(self, tenant_id, lead) -> bool:
        if not lead.status_id:
            return False
        st = self.db.query(Status).filter(Status.id == lead.status_id, Status.tenant_id == tenant_id).first()
        return st is not None and st.key == "won"

    def create_event(self, tenant_id, lid, data: dict, actor) -> dict:
        """Won lead → spawn an event via the EMS capability (repeatable). Hidden in
        the UI when EMS isn't installed; here returns 409 if the capability can't
        resolve (foolproof + backend boundary)."""
        from app.module_platform import resolve_capability

        ld = self.get(tenant_id, lid)
        if not self._is_won(tenant_id, ld):
            raise HTTPException(409, "Win the lead before creating an event from it.")
        handler = resolve_capability(self.db, tenant_id, "project.create_from_template", 1)
        if handler is None:
            raise HTTPException(409, "The Events module is not installed for this workspace.")
        result = handler(
            self.db,
            tenant_id,
            {
                "leadId": ld.id,
                "clientId": ld.client_id,
                "templateId": data["templateId"],
                "title": data.get("title") or ld.title,
            },
        )
        if not result or not result.get("id"):
            raise HTTPException(422, "Could not create the event (check the template).")
        self.db.commit()
        return {"id": result["id"], "title": result.get("title"), "statusId": result.get("statusId")}

    def list_events(self, tenant_id, lid) -> list:
        """Events spawned from this lead — cross-module read via EMS capability."""
        from app.module_platform import resolve_capability

        self.get(tenant_id, lid)  # tenant + existence guard
        handler = resolve_capability(self.db, tenant_id, "projects.by_lead", 1)
        if handler is None:
            return []
        return handler(self.db, tenant_id, {"leadId": lid}) or []


class QuotationService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"createdAt": Quotation.created_at, "revisionNumber": Quotation.revision_number}

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None, client_id=None, latest_only=True):
        from sqlalchemy import func, or_

        q = self.db.query(Quotation).filter(Quotation.tenant_id == tenant_id, Quotation.is_deleted.is_(trashed))
        if ids:
            q = q.filter(Quotation.id.in_(ids))
        if client_id:
            q = q.filter(Quotation.client_id == client_id)
        if latest_only:
            # The list shows ONE row per lineage = the latest revision. A revision
            # is "latest" when no other quotation points at it as a parent.
            superseded = (
                self.db.query(Quotation.parent_quotation_id)
                .filter(Quotation.tenant_id == tenant_id, Quotation.parent_quotation_id.isnot(None))
            )
            q = q.filter(Quotation.id.notin_(superseded))
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(or_(func.lower(Quotation.notes).like(like), func.lower(Quotation.id).like(like)))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="desc", client_id=None):
        q = self._filtered(tenant_id, search=search, trashed=trashed, client_id=client_id)
        col = self._SORT.get(sort_by, Quotation.created_at)
        return _paginate(q.order_by(col.asc() if sort_dir == "asc" else col.desc()), page, page_size)

    def revisions(self, tenant_id, qid) -> list:
        """The full revision lineage of a quotation (oldest→newest), regardless of
        which revision was opened. Walk to the root, then collect the chain down."""
        self.get(tenant_id, qid)  # tenant + existence guard
        rows = (
            self.db.query(Quotation)
            .filter(Quotation.tenant_id == tenant_id, Quotation.is_deleted.is_(False))
            .all()
        )
        by_id = {r.id: r for r in rows}
        # walk up to the root
        root = by_id.get(qid)
        seen = set()
        while root and root.parent_quotation_id and root.parent_quotation_id in by_id and root.id not in seen:
            seen.add(root.id)
            root = by_id[root.parent_quotation_id]
        if root is None:
            return []
        # collect root + all descendants (chain)
        chain, frontier = [], [root.id]
        children = {}
        for r in rows:
            if r.parent_quotation_id:
                children.setdefault(r.parent_quotation_id, []).append(r.id)
        order = []
        stack = [root.id]
        while stack:
            cur = stack.pop(0)
            if cur in chain:
                continue
            chain.append(cur)
            order.append(by_id[cur])
            stack[:0] = children.get(cur, [])
        return sorted(order, key=lambda r: r.revision_number)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _QUOTATION_COLS)

    def get(self, tenant_id, qid) -> Quotation:
        q = self.db.query(Quotation).filter(
            Quotation.id == qid, Quotation.tenant_id == tenant_id, Quotation.is_deleted.is_(False)
        ).first()
        if q is None:
            raise HTTPException(404, "Quotation not found.")
        return q

    def _validate_refs(self, tenant_id, client_id, lead_id, *, require=True):
        if require and not client_id:
            raise HTTPException(422, "A client is required.")
        if client_id is not None:
            ok = self.db.query(Client.id).filter(
                Client.id == client_id, Client.tenant_id == tenant_id, Client.is_deleted.is_(False)
            ).first()
            if ok is None:
                raise HTTPException(422, "Client not found.")
        if lead_id is not None:
            ok = self.db.query(Lead.id).filter(
                Lead.id == lead_id, Lead.tenant_id == tenant_id, Lead.is_deleted.is_(False)
            ).first()
            if ok is None:
                raise HTTPException(422, "Lead not found.")

    def _line_rows(self, tenant_id, qid, lines: list) -> list:
        """Validate product refs against the CORE catalog (polymorphic-id rule),
        derive amount (snapshot-immutable at add)."""
        pids = {ln.get("productId") for ln in lines if ln.get("productId")}
        if pids:
            found = {
                r[0]
                for r in self.db.query(Product.id)
                .filter(Product.tenant_id == tenant_id, Product.is_deleted.is_(False), Product.id.in_(list(pids)))
                .all()
            }
            if pids - found:
                raise HTTPException(422, "A line references a product that doesn't belong to this tenant.")
        out = []
        for i, ln in enumerate(lines):
            qty = Decimal(str(ln.get("qty") or 0))
            unit = Decimal(str(ln.get("unitPrice") or 0))
            out.append(
                QuotationLine(
                    tenant_id=tenant_id,
                    quotation_id=qid,
                    product_id=ln.get("productId"),
                    description=ln.get("description"),
                    qty=qty,
                    unit_price=unit,
                    amount=round(qty * unit, 2),
                    sort=ln.get("sort") if ln.get("sort") is not None else i,
                )
            )
        return out

    def create(self, tenant_id, data: dict, actor) -> Quotation:
        self._validate_refs(tenant_id, data["clientId"], data.get("leadId"))
        currency = data.get("currency") or tenant_default_currency(self.db, tenant_id)
        q = Quotation(
            tenant_id=tenant_id,
            client_id=data["clientId"],
            lead_id=data.get("leadId"),
            project_id=data.get("projectId"),
            currency=currency,
            notes=data.get("notes"),
            revision_number=1,
            status_id=_initial_unscoped(self.db, QUOTATION_ENTITY, tenant_id),
        )
        self.db.add(q)
        self.db.flush()
        for row in self._line_rows(tenant_id, q.id, data.get("lines") or []):
            self.db.add(row)
        self.db.commit()
        self.db.refresh(q)
        return q

    def update(self, tenant_id, qid, data: dict) -> Quotation:
        q = self.get(tenant_id, qid)
        if any(k in data for k in ("clientId", "leadId", "projectId")):
            client_id = data.get("clientId", q.client_id)
            lead_id = data.get("leadId", q.lead_id)
            self._validate_refs(tenant_id, client_id, lead_id)
            q.client_id = client_id
            q.lead_id = lead_id
            q.project_id = data.get("projectId", q.project_id)
        for key, attr in [("currency", "currency"), ("notes", "notes")]:
            if key in data:
                setattr(q, attr, data[key])
        if data.get("lines") is not None:
            new_rows = self._line_rows(tenant_id, q.id, data["lines"])
            q.lines.clear()
            self.db.flush()
            for row in new_rows:
                self.db.add(row)
        self.db.commit()
        self.db.refresh(q)
        return q

    def delete(self, tenant_id, qid) -> None:
        q = self.get(tenant_id, qid)
        q.is_deleted = True
        q.deleted_at = _now()
        self.db.commit()

    def transition(self, tenant_id, qid, to_status_id, actor) -> Quotation:
        q = self.get(tenant_id, qid)
        status_machine.transition(self.db, QUOTATION_ENTITY, q, to_status_id, actor, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(q)
        return q

    def revise(self, tenant_id, qid, actor) -> Quotation:
        src = self.get(tenant_id, qid)
        clone = Quotation(
            tenant_id=tenant_id,
            client_id=src.client_id,
            lead_id=src.lead_id,
            project_id=src.project_id,
            currency=src.currency,
            notes=src.notes,
            revision_number=src.revision_number + 1,
            parent_quotation_id=src.id,
            status_id=_initial_unscoped(self.db, QUOTATION_ENTITY, tenant_id),
        )
        self.db.add(clone)
        self.db.flush()
        for ln in src.lines:
            self.db.add(
                QuotationLine(
                    tenant_id=tenant_id,
                    quotation_id=clone.id,
                    product_id=ln.product_id,
                    description=ln.description,
                    qty=ln.qty,
                    unit_price=ln.unit_price,
                    amount=ln.amount,
                    sort=ln.sort,
                )
            )
        self.db.commit()
        self.db.refresh(clone)
        return clone


def _status_id_by_key(db: Session, entity_type: str, tenant_id: str, key: str):
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


def _status_key_by_id(db: Session, status_id):
    if not status_id:
        return None
    row = db.query(Status).filter(Status.id == status_id).first()
    return row.key if row else None


class SalesOrderService:
    """Sales Order (sprint-4/07, Cluster F slice 2). Created from an Accepted
    quotation or scratch; Confirm assigns the gapless doc_number; "create invoice
    from SO" mints a finance invoice via ``finance.create_invoice@1`` and increments
    invoiced_qty via the CRM ``crm.so_line_invoiced@1`` capability (the seam)."""

    def __init__(self, db: Session):
        self.db = db

    _SORT = {"createdAt": SalesOrder.created_at, "docNumber": SalesOrder.doc_number}

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None, client_id=None):
        from sqlalchemy import func, or_

        q = self.db.query(SalesOrder).filter(
            SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted.is_(trashed)
        )
        if ids:
            q = q.filter(SalesOrder.id.in_(ids))
        if client_id:
            q = q.filter(SalesOrder.client_id == client_id)
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(or_(func.lower(SalesOrder.doc_number).like(like), func.lower(SalesOrder.id).like(like)))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="desc", client_id=None):
        q = self._filtered(tenant_id, search=search, trashed=trashed, client_id=client_id)
        col = self._SORT.get(sort_by, SalesOrder.created_at)
        return _paginate(q.order_by(col.asc() if sort_dir == "asc" else col.desc()), page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _SALES_ORDER_COLS)

    def get(self, tenant_id, sid) -> SalesOrder:
        so = self.db.query(SalesOrder).filter(
            SalesOrder.id == sid, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted.is_(False)
        ).first()
        if so is None:
            raise HTTPException(404, "Sales order not found.")
        return so

    def _validate_client(self, tenant_id, client_id):
        if not client_id:
            raise HTTPException(422, "A client is required.")
        ok = self.db.query(Client.id).filter(
            Client.id == client_id, Client.tenant_id == tenant_id, Client.is_deleted.is_(False)
        ).first()
        if ok is None:
            raise HTTPException(422, "Client not found.")

    def _line_rows(self, tenant_id, sid, lines: list) -> list:
        pids = {ln.get("productId") for ln in lines if ln.get("productId")}
        if pids:
            found = {
                r[0]
                for r in self.db.query(Product.id)
                .filter(Product.tenant_id == tenant_id, Product.is_deleted.is_(False), Product.id.in_(list(pids)))
                .all()
            }
            if pids - found:
                raise HTTPException(422, "A line references a product that doesn't belong to this tenant.")
        out = []
        for i, ln in enumerate(lines):
            qty = Decimal(str(ln.get("qty") or 0))
            unit = Decimal(str(ln.get("unitPrice") or 0))
            rate = Decimal(str(ln.get("taxRate") or 0))
            out.append(
                SalesOrderLine(
                    tenant_id=tenant_id,
                    sales_order_id=sid,
                    product_id=ln.get("productId"),
                    description=ln.get("description"),
                    qty=qty,
                    unit_price=unit,
                    tax_rate=rate,
                    amount=round(qty * unit, 2),
                    invoiced_qty=Decimal(0),
                    sort=ln.get("sort") if ln.get("sort") is not None else i,
                )
            )
        return out

    def create(self, tenant_id, data: dict, actor) -> SalesOrder:
        self._validate_client(tenant_id, data.get("clientId"))
        currency = data.get("currency") or tenant_default_currency(self.db, tenant_id)
        so = SalesOrder(
            tenant_id=tenant_id,
            client_id=data["clientId"],
            quotation_id=data.get("quotationId"),
            project_id=data.get("projectId"),
            currency=currency,
            notes=data.get("notes"),
            status_id=_initial_unscoped(self.db, SALES_ORDER_ENTITY, tenant_id),
        )
        self.db.add(so)
        self.db.flush()
        for row in self._line_rows(tenant_id, so.id, data.get("lines") or []):
            self.db.add(row)
        self.db.commit()
        self.db.refresh(so)
        return so

    def create_from_quotation(self, tenant_id, quotation_id, actor) -> SalesOrder:
        """AC-07-20 — build an SO from an ACCEPTED quotation, copying its lines."""
        q = self.db.query(Quotation).filter(
            Quotation.id == quotation_id, Quotation.tenant_id == tenant_id, Quotation.is_deleted.is_(False)
        ).first()
        if q is None:
            raise HTTPException(404, "Quotation not found.")
        if _status_key_by_id(self.db, q.status_id) != "accepted":
            raise HTTPException(409, "Only an accepted quotation can be turned into a sales order.")
        so = SalesOrder(
            tenant_id=tenant_id,
            client_id=q.client_id,
            quotation_id=q.id,
            project_id=q.project_id,
            currency=q.currency or tenant_default_currency(self.db, tenant_id),
            notes=q.notes,
            status_id=_initial_unscoped(self.db, SALES_ORDER_ENTITY, tenant_id),
        )
        self.db.add(so)
        self.db.flush()
        for ln in q.lines:
            self.db.add(
                SalesOrderLine(
                    tenant_id=tenant_id,
                    sales_order_id=so.id,
                    product_id=ln.product_id,
                    description=ln.description,
                    qty=ln.qty,
                    unit_price=ln.unit_price,
                    tax_rate=Decimal(0),
                    amount=ln.amount,
                    invoiced_qty=Decimal(0),
                    sort=ln.sort,
                )
            )
        self.db.commit()
        self.db.refresh(so)
        return so

    def update(self, tenant_id, sid, data: dict) -> SalesOrder:
        so = self.get(tenant_id, sid)
        # Lines/financials editable only while Draft (mirrors the invoice freeze).
        is_draft = _status_key_by_id(self.db, so.status_id) == "draft"
        if data.get("lines") is not None and not is_draft:
            raise HTTPException(409, "A confirmed sales order's lines are frozen.")
        if "clientId" in data and data["clientId"]:
            self._validate_client(tenant_id, data["clientId"])
            so.client_id = data["clientId"]
        for key, attr in [("currency", "currency"), ("notes", "notes"), ("projectId", "project_id")]:
            if key in data:
                setattr(so, attr, data[key])
        if data.get("lines") is not None and is_draft:
            new_rows = self._line_rows(tenant_id, so.id, data["lines"])
            so.lines.clear()
            self.db.flush()
            for row in new_rows:
                self.db.add(row)
        self.db.commit()
        self.db.refresh(so)
        return so

    def delete(self, tenant_id, sid) -> None:
        so = self.get(tenant_id, sid)
        so.is_deleted = True
        so.deleted_at = _now()
        self.db.commit()

    def transition(self, tenant_id, sid, to_status_id, actor) -> SalesOrder:
        """Status move. Confirm assigns the gapless doc_number in the SAME commit
        (AC-07-19)."""
        so = self.get(tenant_id, sid)
        target_key = _status_key_by_id(self.db, to_status_id)
        status_machine.transition(
            self.db, SALES_ORDER_ENTITY, so, to_status_id, actor, tenant_id=tenant_id, commit=False
        )
        if target_key == "confirmed" and not so.doc_number:
            from app.services.numbering_service import NumberingService

            now = _now()
            so.doc_number = NumberingService(self.db).next_number(tenant_id, "sales_order", now.date())
            so.confirmed_at = now
            self.db.flush()
        self.db.commit()
        self.db.refresh(so)
        return so

    # ── create invoice from SO (AC-07-21/22) ──
    def create_invoice_from_so(self, tenant_id, sid, selections: list, actor) -> dict:
        """Mint a finance invoice for chosen lines + quantities, link sales_order_id,
        and increment each line's invoiced_qty via the CRM capability (the seam).

        ``selections`` = [{lineId, qty}]. ``qty`` ≤ the line's remaining (qty −
        invoiced_qty). Returns the created invoice dict (id/total/currency)."""
        from app.module_platform import resolve_capability

        # Lock the SO row so two concurrent invoicings serialise on the
        # remaining-qty check → invoiced_qty increment (no over-invoicing race).
        so = self.db.query(SalesOrder).filter(
            SalesOrder.id == sid, SalesOrder.tenant_id == tenant_id,
            SalesOrder.is_deleted.is_(False),
        ).with_for_update().first()
        if so is None:
            raise HTTPException(404, "Sales order not found.")
        if _status_key_by_id(self.db, so.status_id) != "confirmed":
            raise HTTPException(409, "Confirm the sales order before invoicing it.")
        lines_by_id = {ln.id: ln for ln in so.lines}
        invoice_lines = []
        applied = []
        for sel in selections:
            line = lines_by_id.get(sel.get("lineId"))
            if line is None:
                raise HTTPException(422, "A selected line doesn't belong to this sales order.")
            qty = Decimal(str(sel.get("qty") or 0))
            remaining = Decimal(str(line.qty)) - Decimal(str(line.invoiced_qty or 0))
            if qty <= 0:
                continue
            if qty > remaining:
                raise HTTPException(409, "Cannot invoice more than the remaining quantity on a line.")
            invoice_lines.append({
                "projectProductId": line.product_id,
                "description": line.description,
                "qty": int(qty),
                "unitPrice": float(line.unit_price),
                "taxRate": float(Decimal(str(line.tax_rate or 0)) * Decimal(100)),
            })
            applied.append((line.id, qty))
        if not invoice_lines:
            raise HTTPException(422, "Select at least one line with a quantity to invoice.")

        create = resolve_capability(self.db, tenant_id, "finance.create_invoice", 1)
        if create is None:
            raise HTTPException(409, "The Finance module is not installed for this workspace.")
        result = create(self.db, tenant_id, {
            "billToType": "Client",
            "billToId": so.client_id,
            "currency": so.currency,
            "projectId": so.project_id,
            "salesOrderId": so.id,
            "lines": invoice_lines,
        })
        if not result or not result.get("id"):
            raise HTTPException(422, "Could not create the invoice.")

        # Increment each invoiced line via the OWN capability (exercises the seam,
        # AC-07-22). Same session/transaction — the invoice + the denorm commit
        # together. The capability emits the line event so Fulfilled re-derives.
        invoiced = resolve_capability(self.db, tenant_id, "crm.so_line_invoiced", 1)
        for line_id, qty in applied:
            invoiced(self.db, tenant_id, {"soLineId": line_id, "qty": float(qty)})
        self.db.commit()
        return {"id": result["id"], "total": result.get("total"), "currency": result.get("currency")}

    # ── capability handler: crm.so_line_invoiced@1 (AC-07-22) ──
    def apply_line_invoiced(self, tenant_id, line_id, qty) -> dict:
        """Increment a line's invoiced_qty (finance is the caller; CRM owns the
        number). Tenant-scoped; emits the line event so the SO re-derives Fulfilled.
        Does NOT commit — the caller owns the transaction."""
        line = (
            self.db.query(SalesOrderLine)
            .filter(SalesOrderLine.id == line_id, SalesOrderLine.tenant_id == tenant_id)
            .first()
        )
        if line is None:
            raise HTTPException(404, "Sales order line not found.")
        line.invoiced_qty = Decimal(str(line.invoiced_qty or 0)) + Decimal(str(qty))
        self.db.flush()
        # Re-derive the owning SO (Fulfilled). BUFFER the line event here (the
        # caller commits AFTER this, so a drain-now would run on a fresh session
        # that can't see the uncommitted invoiced_qty); the after-commit drain
        # fires once the caller commits and sees the new value.
        from app.workflow_engine.entity_events import emit_entity_event

        emit_entity_event(
            self.db, "sales_order_line", "updated", line, tenant_id=tenant_id, actor=None
        )
        return {"lineId": line.id, "invoicedQty": float(line.invoiced_qty)}

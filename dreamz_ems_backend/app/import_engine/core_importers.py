"""Core importer configs (sprint-3/09). First opt-in target = ``user`` — proves
the engine end-to-end before F4 consumes it (plan 11 adds profile/participant).

Columns ⊆ the entity's workflow ``writable`` whitelist + ``email`` (a natural key
that is unique-validated but never a match key — matching is id-only, D5). The
drift-guard test asserts the subset relationship.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from decimal import Decimal, InvalidOperation

from app.import_engine.registry import (
    ImportColumn,
    ImporterDef,
    register_importer,
)
from app.models.catalog import Product, ProductCategory
from app.models.user import User, UserStatus

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STATUS_OPTIONS = [{"value": s.value, "label": s.value.title()} for s in UserStatus]


def _valid_email(value) -> str | None:
    if value and not _EMAIL_RE.match(str(value)):
        return "not a valid email address"
    return None


def _user_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    rows = (
        db.query(User.id)
        .filter(User.tenant_id == tenant_id, User.id.in_(ids))
        .all()
    )
    return {r[0] for r in rows}


def _user_email_lookup(db: Session, tenant_id: str, emails: List[str]) -> Dict[str, str]:
    """Batched table-existence for the unique email guard (set-based)."""
    lowered = [e.lower() for e in emails]
    rows = (
        db.query(User.email)
        .filter(User.tenant_id == tenant_id)
        .all()
    )
    existing = {r[0].lower() for r in rows}
    return {e: e for e in emails if e.lower() in existing}


def _create_users(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    """Set-based bulk insert (D7). Email uniqueness across the table is enforced
    by validation; the DB UNIQUE backstops a race."""
    now = datetime.now(timezone.utc)
    mappings = []
    ids = []
    for r in rows:
        uid = str(uuid.uuid4())
        ids.append(uid)
        mappings.append(
            {
                "id": uid,
                "tenant_id": tenant_id,
                "email": r["email"],
                "name": r.get("name"),
                "status": r.get("status") or UserStatus.INACTIVE.value,
                "password": None,
                "is_trashed": False,
                "created_at": now,
                "updated_at": now,
                "avatar_version": 0,
            }
        )
    if mappings:
        db.bulk_insert_mappings(User, mappings)
    return ids


def _update_users(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    """Partial update — only present columns written, absent untouched (D5)."""
    ids = []
    for r in rows:
        patch = {k: v for k, v in r.items() if k != "id" and v is not None}
        if not patch:
            ids.append(r["id"])
            continue
        db.query(User).filter(
            User.tenant_id == tenant_id, User.id == r["id"]
        ).update(patch, synchronize_session=False)
        ids.append(r["id"])
    return ids


# ── product importer (core catalog) ──────────────────────────────────────────


def _num(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _valid_number(v):
    if v in (None, ""):
        return None
    try:
        Decimal(str(v))
        return None
    except (InvalidOperation, TypeError, ValueError):
        return "must be a number"


def _valid_kind(v):
    if not v:
        return None
    from app.catalog.kinds import all_kinds

    keys = {k.key for k in all_kinds()}
    return None if str(v).lower() in keys else f"must be one of {', '.join(sorted(keys))}"


def _product_existing_ids(db: Session, tenant_id: str, ids: List[str]) -> set:
    return {
        r[0]
        for r in db.query(Product.id).filter(Product.tenant_id == tenant_id, Product.id.in_(ids)).all()
    }


def _validate_product_refs(db: Session, tenant_id: str, rows: List[dict]) -> None:
    from fastapi import HTTPException

    wanted = {r.get("categoryId") for r in rows if r.get("categoryId")}
    if not wanted:
        return
    found = {
        r[0]
        for r in db.query(ProductCategory.id)
        .filter(ProductCategory.tenant_id == tenant_id, ProductCategory.id.in_(list(wanted)))
        .all()
    }
    missing = wanted - found
    if missing:
        raise HTTPException(422, f"These category IDs don't belong to this tenant: {', '.join(sorted(missing))}")


_PRODUCT_FIELDS = {"name": "name", "sku": "sku", "uom": "uom", "categoryId": "category_id", "currency": "currency"}


def _create_products(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    _validate_product_refs(db, tenant_id, rows)
    now = datetime.now(timezone.utc)
    ids, mappings = [], []
    for r in rows:
        pid = str(uuid.uuid4())
        ids.append(pid)
        m = {
            "id": pid, "tenant_id": tenant_id, "is_deleted": False,
            "kind": str(r.get("kind") or "service").lower(),
            "default_price": _num(r.get("defaultPrice")),
            "tax": _num(r.get("tax")),
            "is_active": True,
            "created_at": now, "updated_at": now,
        }
        for key, attr in _PRODUCT_FIELDS.items():
            m[attr] = r.get(key)
        mappings.append(m)
    if mappings:
        db.bulk_insert_mappings(Product, mappings)
    return ids


def _update_products(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    _validate_product_refs(db, tenant_id, rows)
    ids = []
    for r in rows:
        patch = {attr: r[key] for key, attr in _PRODUCT_FIELDS.items() if r.get(key) is not None}
        if r.get("kind"):
            patch["kind"] = str(r["kind"]).lower()
        if _num(r.get("defaultPrice")) is not None:
            patch["default_price"] = _num(r.get("defaultPrice"))
        if _num(r.get("tax")) is not None:
            patch["tax"] = _num(r.get("tax"))
        if patch:
            db.query(Product).filter(Product.tenant_id == tenant_id, Product.id == r["id"]).update(
                patch, synchronize_session=False
            )
        ids.append(r["id"])
    return ids


def register_core_importers() -> None:
    register_importer(
        ImporterDef(
            entity_type="product",
            label="Product",
            model=Product,
            columns=(
                ImportColumn(key="id", label="ID", type="string"),
                ImportColumn(key="name", label="Name", type="string", required=True),
                ImportColumn(key="sku", label="SKU", type="string"),
                ImportColumn(
                    key="kind", label="Kind", type="string",
                    transform=lambda v: str(v).lower() if v else v, validators=(_valid_kind,),
                ),
                ImportColumn(key="categoryId", label="Category ID", type="string"),
                ImportColumn(key="defaultPrice", label="Default price", type="string", validators=(_valid_number,)),
                ImportColumn(key="tax", label="Tax", type="string", validators=(_valid_number,)),
                ImportColumn(key="currency", label="Currency", type="string"),
                ImportColumn(key="uom", label="Unit of measure", type="string"),
            ),
            create_rows=_create_products,
            update_rows=_update_products,
            existing_ids=_product_existing_ids,
            module="core",
            write_permission="products.create",
        )
    )
    register_importer(
        ImporterDef(
            entity_type="user",
            label="User",
            model=User,
            columns=(
                ImportColumn(key="id", label="ID", type="string"),  # match key (update/upsert)
                ImportColumn(
                    key="email",
                    label="Email",
                    type="string",
                    required=True,
                    unique=True,
                    transform=lambda v: str(v).strip().lower(),
                    validators=(_valid_email,),
                ),
                ImportColumn(key="name", label="Name", type="string"),
                ImportColumn(
                    key="status",
                    label="Status",
                    type="enum",
                    options=_STATUS_OPTIONS,
                ),
            ),
            create_rows=_create_users,
            update_rows=_update_users,
            existing_ids=_user_existing_ids,
            module="core",
            write_permission="users.create",
        )
    )

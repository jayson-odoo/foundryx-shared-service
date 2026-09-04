"""Core catalog services (sprint-4/08) - Service-Repository, tenant-scoped.

Products + categories are core/horizontal. ``kind`` validated against the active
product-kind registry (metadata, not a behavior branch). Product delete is
SOFT-only and BLOCKED (409) while any module's reference-guard reports it in use.
Effective currency = product override else the tenant default.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.catalog.kinds import is_valid_kind, kind_label
from app.models.catalog import Product, ProductCategory
from app.models.tenant_settings import (
    DEFAULT_CURRENCY,
    DEFAULT_DEFERRED_DESTRUCTIVE_SECONDS,
    DEFAULT_DEFERRED_REVERSIBLE_SECONDS,
    DEFAULT_PRICE_DECIMALS,
    TenantSettings,
)
from app.module_platform import reference_counts

PRODUCT_ENTITY = "product"


def _now():
    return datetime.now(timezone.utc)


def _iso(v):
    return v.isoformat() if v else ""


def _paginate(query, page, page_size):
    total = query.count()
    rows = query.offset(page * page_size).limit(page_size).all()
    return rows, total


_PRODUCT_COLS = {
    "id": lambda r: r.id,
    "name": lambda r: r.name,
    "sku": lambda r: r.sku or "",
    "kind": lambda r: r.kind,
    "categoryId": lambda r: r.category_id or "",
    "defaultPrice": lambda r: "" if r.default_price is None else float(r.default_price),
    "tax": lambda r: "" if r.tax is None else float(r.tax),
    "currency": lambda r: r.currency or "",
    "uom": lambda r: r.uom or "",
    "isActive": lambda r: r.is_active,
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


# ── tenant default currency ──────────────────────────────────────────────────


class TenantSettingsService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str) -> dict:
        row = self.db.get(TenantSettings, tenant_id)
        return {
            "defaultCurrency": (row.default_currency if row and row.default_currency else DEFAULT_CURRENCY),
            "priceDecimals": (
                row.price_decimals if row and row.price_decimals is not None else DEFAULT_PRICE_DECIMALS
            ),
            "deferredDestructiveSeconds": (
                row.deferred_destructive_seconds
                if row and row.deferred_destructive_seconds is not None
                else DEFAULT_DEFERRED_DESTRUCTIVE_SECONDS
            ),
            "deferredReversibleSeconds": (
                row.deferred_reversible_seconds
                if row and row.deferred_reversible_seconds is not None
                else DEFAULT_DEFERRED_REVERSIBLE_SECONDS
            ),
        }

    def set(self, tenant_id: str, data: dict) -> dict:
        row = self.db.get(TenantSettings, tenant_id)
        if row is None:
            row = TenantSettings(tenant_id=tenant_id)
            self.db.add(row)
        if "defaultCurrency" in data and data["defaultCurrency"]:
            cur = str(data["defaultCurrency"]).strip().upper()
            if len(cur) != 3 or not cur.isalpha():
                raise HTTPException(422, "Currency must be a 3-letter ISO code.")
            row.default_currency = cur
        if "priceDecimals" in data and data["priceDecimals"] is not None:
            dp = int(data["priceDecimals"])
            if dp < 0 or dp > 6:
                raise HTTPException(422, "Decimal places must be between 0 and 6.")
            row.price_decimals = dp
        if "deferredDestructiveSeconds" in data and data["deferredDestructiveSeconds"] is not None:
            secs = int(data["deferredDestructiveSeconds"])
            if secs < 1 or secs > 60:
                raise HTTPException(422, "Delete countdown must be between 1 and 60 seconds.")
            row.deferred_destructive_seconds = secs
        if "deferredReversibleSeconds" in data and data["deferredReversibleSeconds"] is not None:
            secs = int(data["deferredReversibleSeconds"])
            if secs < 1 or secs > 60:
                raise HTTPException(422, "Reversible countdown must be between 1 and 60 seconds.")
            row.deferred_reversible_seconds = secs
        self.db.commit()
        return self.get(tenant_id)


def tenant_default_currency(db: Session, tenant_id: str) -> str:
    row = db.get(TenantSettings, tenant_id)
    return row.default_currency if row and row.default_currency else DEFAULT_CURRENCY


# ── categories ───────────────────────────────────────────────────────────────


class CategoryService:
    """Product category taxonomy tree - list returns the whole tenant set; the
    frontend builds the tree (reusable Resource-shell tree mode)."""

    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id):
        return (
            self.db.query(ProductCategory)
            .filter(ProductCategory.tenant_id == tenant_id, ProductCategory.is_deleted.is_(False))
            .order_by(ProductCategory.sort.asc().nullslast(), ProductCategory.name.asc())
            .all()
        )

    def get(self, tenant_id, cid) -> ProductCategory:
        c = (
            self.db.query(ProductCategory)
            .filter(
                ProductCategory.id == cid,
                ProductCategory.tenant_id == tenant_id,
                ProductCategory.is_deleted.is_(False),
            )
            .first()
        )
        if c is None:
            raise HTTPException(404, "Category not found.")
        return c

    def _validate_parent(self, tenant_id, parent_id, *, child_id=None):
        if parent_id is None:
            return
        if parent_id == child_id:
            raise HTTPException(422, "A category can't be its own parent.")
        self.get(tenant_id, parent_id)
        if child_id is not None:
            seen = set()
            cur = parent_id
            while cur is not None and cur not in seen:
                if cur == child_id:
                    raise HTTPException(422, "That move would create a cycle in the tree.")
                seen.add(cur)
                row = (
                    self.db.query(ProductCategory.parent_id)
                    .filter(ProductCategory.id == cur, ProductCategory.tenant_id == tenant_id)
                    .first()
                )
                cur = row[0] if row else None

    def create(self, tenant_id, data: dict) -> ProductCategory:
        self._validate_parent(tenant_id, data.get("parentId"))
        c = ProductCategory(
            tenant_id=tenant_id,
            name=data["name"],
            parent_id=data.get("parentId"),
            sort=data.get("sort"),
        )
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def update(self, tenant_id, cid, data: dict) -> ProductCategory:
        c = self.get(tenant_id, cid)
        if "parentId" in data:
            self._validate_parent(tenant_id, data["parentId"], child_id=cid)
            c.parent_id = data["parentId"]
        if data.get("name") is not None:
            c.name = data["name"]
        if "sort" in data:
            c.sort = data["sort"]
        self.db.commit()
        self.db.refresh(c)
        return c

    def delete(self, tenant_id, cid) -> None:
        c = self.get(tenant_id, cid)
        kid = (
            self.db.query(ProductCategory.id)
            .filter(
                ProductCategory.tenant_id == tenant_id,
                ProductCategory.parent_id == cid,
                ProductCategory.is_deleted.is_(False),
            )
            .first()
        )
        if kid is not None:
            raise HTTPException(409, "This category has sub-categories. Move or delete them first.")
        prod = (
            self.db.query(Product.id)
            .filter(
                Product.tenant_id == tenant_id,
                Product.category_id == cid,
                Product.is_deleted.is_(False),
            )
            .first()
        )
        if prod is not None:
            raise HTTPException(409, "This category still has products. Move or delete them first.")
        c.is_deleted = True
        self.db.commit()


# ── products ─────────────────────────────────────────────────────────────────


class ProductService:
    def __init__(self, db: Session):
        self.db = db

    _SORT = {"name": Product.name, "sku": Product.sku, "createdAt": Product.created_at}

    def _filtered(self, tenant_id, *, search=None, trashed=False, ids=None):
        from sqlalchemy import func, or_

        q = self.db.query(Product).filter(
            Product.tenant_id == tenant_id, Product.is_deleted.is_(trashed)
        )
        if ids:
            q = q.filter(Product.id.in_(ids))
        if search:
            like = f"%{search.lower()}%"
            q = q.filter(or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like)))
        return q

    def list(self, tenant_id, *, search=None, page=0, page_size=25, trashed=False, sort_by=None, sort_dir="asc"):
        q = self._filtered(tenant_id, search=search, trashed=trashed)
        col = self._SORT.get(sort_by, Product.created_at)
        q = q.order_by(col.asc() if sort_dir == "asc" else col.desc())
        return _paginate(q, page, page_size)

    def export_csv(self, tenant_id, columns, *, ids=None, search=None, trashed=False):
        rows = self._filtered(tenant_id, search=search, trashed=trashed, ids=ids).all()
        return _csv(columns, rows, _PRODUCT_COLS)

    def options(self, tenant_id, *, search=None, limit=20):
        """(id, name, price, currency) picker for quotation lines - active only."""
        q = self.db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
        if search:
            from sqlalchemy import func

            q = q.filter(func.lower(Product.name).like(f"%{search.lower()}%"))
        return q.order_by(Product.name.asc()).limit(limit).all()

    def get(self, tenant_id, pid) -> Product:
        p = self.db.query(Product).filter(
            Product.id == pid, Product.tenant_id == tenant_id
        ).first()
        if p is None:
            raise HTTPException(404, "Product not found.")
        return p

    def _validate(self, tenant_id, kind=None, category_id=None):
        if kind is not None and not is_valid_kind(self.db, tenant_id, kind):
            raise HTTPException(422, "Unknown product kind for this workspace.")
        if category_id is not None:
            ok = (
                self.db.query(ProductCategory.id)
                .filter(
                    ProductCategory.id == category_id,
                    ProductCategory.tenant_id == tenant_id,
                    ProductCategory.is_deleted.is_(False),
                )
                .first()
            )
            if ok is None:
                raise HTTPException(422, "Category not found.")

    def create(self, tenant_id, data: dict) -> Product:
        kind = data.get("kind") or "service"
        self._validate(tenant_id, kind, data.get("categoryId"))
        cur = data.get("currency")
        p = Product(
            tenant_id=tenant_id,
            name=data["name"],
            kind=kind,
            category_id=data.get("categoryId"),
            sku=data.get("sku"),
            default_price=data.get("defaultPrice"),
            tax=data.get("tax"),
            currency=(str(cur).strip().upper() if cur else None),
            uom=data.get("uom"),
            is_active=data.get("isActive", True),
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def update(self, tenant_id, pid, data: dict) -> Product:
        p = self.get(tenant_id, pid)
        self._validate(
            tenant_id,
            data.get("kind") if "kind" in data else None,
            data.get("categoryId") if data.get("categoryId") else None,
        )
        for key, attr in [
            ("name", "name"), ("kind", "kind"), ("sku", "sku"),
            ("defaultPrice", "default_price"), ("tax", "tax"), ("uom", "uom"),
        ]:
            if key in data and data[key] is not None:
                setattr(p, attr, data[key])
        if "currency" in data:
            cur = data["currency"]
            p.currency = str(cur).strip().upper() if cur else None
        if "categoryId" in data:
            p.category_id = data["categoryId"]
        if "isActive" in data and data["isActive"] is not None:
            p.is_active = data["isActive"]
        self.db.commit()
        self.db.refresh(p)
        return p

    def delete(self, tenant_id, pid) -> None:
        """Soft-delete only, BLOCKED while referenced (reference-guard registry)."""
        p = self.get(tenant_id, pid)
        refs = reference_counts(self.db, tenant_id, PRODUCT_ENTITY, pid)
        if refs:
            where = ", ".join(f"{n} {label}" for label, n in refs.items())
            raise HTTPException(409, f"Can't delete: product is used in {where}.")
        p.is_deleted = True
        self.db.commit()

"""Core catalog routes (sprint-4/08) — products + categories (horizontal,
``public``) + tenant general settings (default currency). Thin: validation +
responses only. Gated products.* / product_categories.* / settings.*."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.catalog.kinds import active_kinds, kind_label
from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.catalog import (
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    ExportRequest,
    ListResponse,
    ProductIn,
    ProductKindOut,
    ProductOut,
    ProductPatch,
    TenantSettingsOut,
    TenantSettingsPatch,
)
from app.services.catalog_service import (
    CategoryService,
    ProductService,
    TenantSettingsService,
)

products_router = APIRouter()
categories_router = APIRouter()
settings_router = APIRouter()


def _product_out(r) -> ProductOut:
    return ProductOut.from_row(r, kind_label(r.kind))


# ── products ─────────────────────────────────────────────────────────────────


@products_router.get("", response_model=ListResponse)
def list_products(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
    current_user: User = Depends(require_permission("products.read")),
    db: Session = Depends(get_db),
):
    rows, total = ProductService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir,
    )
    return ListResponse(items=[_product_out(r) for r in rows], total=total, page=page, pageSize=page_size)


@products_router.get("/kinds", response_model=list[ProductKindOut])
def list_product_kinds(
    current_user: User = Depends(require_permission("products.read")),
    db: Session = Depends(get_db),
):
    return [ProductKindOut(key=k.key, label=k.label) for k in active_kinds(db, current_user.tenant_id)]


@products_router.get("/options", response_model=list[ProductOut])
def product_options(
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("products.read")),
    db: Session = Depends(get_db),
):
    rows = ProductService(db).options(current_user.tenant_id, search=search)
    return [_product_out(r) for r in rows]


@products_router.post("/export", response_class=PlainTextResponse)
def export_products(
    body: ExportRequest,
    current_user: User = Depends(require_permission("products.read")),
    db: Session = Depends(get_db),
):
    csv_text = ProductService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@products_router.post("", response_model=ProductOut, status_code=201)
def create_product(
    body: ProductIn,
    current_user: User = Depends(require_permission("products.create")),
    db: Session = Depends(get_db),
):
    return _product_out(ProductService(db).create(current_user.tenant_id, body.model_dump()))


@products_router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: str,
    current_user: User = Depends(require_permission("products.read")),
    db: Session = Depends(get_db),
):
    return _product_out(ProductService(db).get(current_user.tenant_id, product_id))


@products_router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: str,
    body: ProductPatch,
    current_user: User = Depends(require_permission("products.update")),
    db: Session = Depends(get_db),
):
    return _product_out(
        ProductService(db).update(current_user.tenant_id, product_id, body.model_dump(exclude_unset=True))
    )


@products_router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: str,
    current_user: User = Depends(require_permission("products.delete")),
    db: Session = Depends(get_db),
):
    ProductService(db).delete(current_user.tenant_id, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── categories ───────────────────────────────────────────────────────────────


@categories_router.get("", response_model=list[CategoryOut])
def list_categories(
    current_user: User = Depends(require_permission("product_categories.read")),
    db: Session = Depends(get_db),
):
    return [CategoryOut.model_validate(c) for c in CategoryService(db).list(current_user.tenant_id)]


@categories_router.post("", response_model=CategoryOut, status_code=201)
def create_category(
    body: CategoryIn,
    current_user: User = Depends(require_permission("product_categories.manage")),
    db: Session = Depends(get_db),
):
    return CategoryOut.model_validate(CategoryService(db).create(current_user.tenant_id, body.model_dump()))


@categories_router.get("/{category_id}", response_model=CategoryOut)
def get_category(
    category_id: str,
    current_user: User = Depends(require_permission("product_categories.read")),
    db: Session = Depends(get_db),
):
    return CategoryOut.model_validate(CategoryService(db).get(current_user.tenant_id, category_id))


@categories_router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: str,
    body: CategoryPatch,
    current_user: User = Depends(require_permission("product_categories.manage")),
    db: Session = Depends(get_db),
):
    return CategoryOut.model_validate(
        CategoryService(db).update(current_user.tenant_id, category_id, body.model_dump(exclude_unset=True))
    )


@categories_router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: str,
    current_user: User = Depends(require_permission("product_categories.manage")),
    db: Session = Depends(get_db),
):
    CategoryService(db).delete(current_user.tenant_id, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── tenant general settings (default currency) ───────────────────────────────


@settings_router.get("/general", response_model=TenantSettingsOut)
def get_general_settings(
    current_user: User = Depends(require_permission("settings.read")),
    db: Session = Depends(get_db),
):
    return TenantSettingsOut(**TenantSettingsService(db).get(current_user.tenant_id))


@settings_router.put("/general", response_model=TenantSettingsOut)
def update_general_settings(
    body: TenantSettingsPatch,
    current_user: User = Depends(require_permission("settings.update")),
    db: Session = Depends(get_db),
):
    return TenantSettingsOut(
        **TenantSettingsService(db).set(current_user.tenant_id, body.model_dump(exclude_unset=True))
    )

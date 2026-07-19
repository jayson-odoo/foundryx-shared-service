"""Ideation product delivery-config routes (AC-A-06 / AC-A-08).

Product CRUD REUSES the core catalog API (``/products``, ``products.*`` perms) —
NOT duplicated here. This router owns only the ideation delivery extension: the
software Product's ``product_domain_base``. Gated by ``require_module("ideation")``
(injected by the module loader) + ``ideation.products.manage`` (Maintainer)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import DeliveryConfigIn, DeliveryConfigOut
from ..services.products import DeliveryService

router = APIRouter()


def _out(product_id: str, row) -> DeliveryConfigOut:
    if row is None:
        return DeliveryConfigOut(productId=product_id, productDomainBase=None)
    return DeliveryConfigOut(
        productId=row.product_id,
        productDomainBase=row.product_domain_base,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


@router.get("/{product_id}/delivery", response_model=DeliveryConfigOut)
def get_delivery(
    product_id: str,
    current_user: User = Depends(require_permission("ideation.products.manage")),
    db: Session = Depends(get_db),
) -> DeliveryConfigOut:
    row = DeliveryService(db).get(current_user.tenant_id, product_id)
    return _out(product_id, row)


@router.put("/{product_id}/delivery", response_model=DeliveryConfigOut)
def set_delivery(
    product_id: str,
    body: DeliveryConfigIn,
    current_user: User = Depends(require_permission("ideation.products.manage")),
    db: Session = Depends(get_db),
) -> DeliveryConfigOut:
    row = DeliveryService(db).set(
        current_user.tenant_id, product_id, body.productDomainBase
    )
    return _out(product_id, row)

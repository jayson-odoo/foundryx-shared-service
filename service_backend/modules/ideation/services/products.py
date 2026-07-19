"""Software-product delivery config service (AC-A-06 / AC-A-08).

Product CRUD is the CORE catalog's job (``/products``, ``products.*``); this
service owns ONLY the ideation delivery extension (``product_delivery``): the
validated ``product_domain_base`` origin that mints product-domain idea links.
"""
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product

from ..models import ProductDelivery


def validate_origin(value: str) -> str:
    """A ``product_domain_base`` must be an ABSOLUTE http(s) origin with no path,
    query or fragment (e.g. ``https://fe-sorento.foundryx.my``). Returns the
    normalized ``scheme://host[:port]`` (a single trailing slash is tolerated and
    stripped) so link minting (``{base}/ideas/{id}``) is always clean; anything
    else is a 422."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "product_domain_base must be an absolute http(s) origin.")
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        raise HTTPException(422, "product_domain_base must be an origin with no path.")
    return f"{parsed.scheme}://{parsed.netloc}"


class DeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def _product_or_404(self, tenant_id: str, product_id: str) -> Product:
        p = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )
        if p is None:
            raise HTTPException(404, "Product not found.")
        return p

    def _row(self, tenant_id: str, product_id: str) -> ProductDelivery | None:
        return (
            self.db.query(ProductDelivery)
            .filter(
                ProductDelivery.tenant_id == tenant_id,
                ProductDelivery.product_id == product_id,
            )
            .first()
        )

    def get(self, tenant_id: str, product_id: str) -> ProductDelivery | None:
        """Delivery row for a product (404 if the product itself is missing;
        ``None`` if the product exists but has no delivery config yet)."""
        self._product_or_404(tenant_id, product_id)
        return self._row(tenant_id, product_id)

    def set(self, tenant_id: str, product_id: str, product_domain_base: str) -> ProductDelivery:
        """Upsert the delivery config (one row per product). 404 if the product
        is missing; 422 if the origin is invalid."""
        self._product_or_404(tenant_id, product_id)
        origin = validate_origin(product_domain_base)
        row = self._row(tenant_id, product_id)
        if row is None:
            row = ProductDelivery(tenant_id=tenant_id, product_id=product_id)
            self.db.add(row)
        row.product_domain_base = origin
        self.db.commit()
        self.db.refresh(row)
        return row

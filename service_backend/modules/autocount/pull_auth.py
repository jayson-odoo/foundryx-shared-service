"""Sprint-5/10 S4 - the public pull gateway's auth + throttle (AC-10-30/31/35).

``resolve_pull_key`` is the public-route sibling of core ``get_current_user``:
resolves ``X-API-Key`` to a tenant-scoped ``AcPullApiKey`` row - never
trusting the request body/query for tenancy or company scope. Every failure
raises ``PullGatewayError``, rendered by the router into the FLAT Appendix A6
envelope (``{code,message,companyCode,entity}``) - never core's
``{"error": {...}}`` ``/api/v1/*`` wrapper (``app/api_errors.py``).

Throttle is enforced BEFORE key resolution (AC-10-35): a 401 (missing/
malformed/unknown/revoked key) records ONE failure on the caller's IP under
the ``pull`` scope; every other outcome (403/404/409/429/2xx) never touches
the bucket - the gateway's own business gates (one ``building`` snapshot per
triple, the 60s build cooldown) bound volume structurally.
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import Throttled, ThrottleService, client_ip

from .bootstrap import MODULE_NAME
from .models import AcPullApiKey
from .services.pull_key_service import PullKeyService


class PullGatewayError(Exception):
    """Raised by any gateway auth/business check; ``to_response()`` renders
    the flat Appendix A6 body. ``company_code``/``entity`` are filled in at
    the raise site when already known (e.g. from a found snapshot, or from
    the POST body); the caller backfills the rest via ``with_context`` once
    it has parsed the request - the two GET routes have nothing to backfill
    and stay ``null``, which is deliberate (stated once in the plan/UAC)."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        company_code: Optional[str] = None,
        entity: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        company_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.company_code = company_code
        self.entity = entity
        # Audit-only context (never rendered on the wire) - so a failure that
        # already resolved a snapshot/company/entity still writes an
        # attributable audit row (AC-10-34).
        self.snapshot_id = snapshot_id
        self.company_id = company_id
        self.entity_type = entity_type
        self.headers: Dict[str, str] = {}

    def with_retry_after(self, seconds: int) -> "PullGatewayError":
        self.headers["Retry-After"] = str(int(seconds))
        return self

    def with_context(
        self, *, company_code: Optional[str] = None, entity: Optional[str] = None
    ) -> "PullGatewayError":
        """Backfill ``companyCode``/``entity`` from the request when the
        raise site did not already know them (e.g. a 401 raised before the
        POST body was inspected)."""
        if self.company_code is None:
            self.company_code = company_code
        if self.entity is None:
            self.entity = entity
        return self

    def to_response(self) -> JSONResponse:
        body = {
            "code": self.code,
            "message": self.message,
            "companyCode": self.company_code,
            "entity": self.entity,
        }
        # Security round 1 MEDIUM 6 - this surface serves a customer's ERP
        # master data behind a bearer-style key; nothing on it is ever
        # cacheable by an intermediary, success OR error.
        headers = {"Cache-Control": "no-store"}
        headers.update(self.headers)
        return JSONResponse(status_code=self.status_code, content=body, headers=headers)


def _service_enabled(db: Session, tenant_id: str) -> bool:
    """The SAME predicate ``scheduler.sweep_etl_tasks`` uses: the tenant's
    own lifecycle chokepoint (``Tenant.signin_allowed`` - not blocked, not
    archived) AND the module active for this tenant. Neither check trusts
    anything the caller sent."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def resolve_pull_key(request: Request, db: Session) -> AcPullApiKey:
    """Enforces the ``pull`` throttle scope, then resolves ``X-API-Key``,
    then the per-KEY request budget.

    Raises ``PullGatewayError``: 429 ``TOO_MANY_REQUESTS`` (over the IP
    throttle, before key resolution even runs, OR over the per-key budget
    below), 401 ``INVALID_API_KEY`` (missing/malformed/unknown/revoked,
    uniform - no oracle), 403 ``SERVICE_NOT_ENABLED`` (module inactive for
    this tenant, or the tenant is suspended/archived).
    """
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_pull(ip=ip)
    except Throttled as exc:
        raise PullGatewayError(
            429, "TOO_MANY_REQUESTS", "Too many failed attempts. Try again shortly."
        ).with_retry_after(exc.retry_after_seconds)

    presented = request.headers.get("x-api-key")
    key_row = PullKeyService(db).resolve(presented)
    if key_row is None:
        throttle.record_pull_failure(ip=ip)
        raise PullGatewayError(
            401, "INVALID_API_KEY", "Missing, malformed, unknown or revoked key."
        )
    if not _service_enabled(db, key_row.tenant_id):
        raise PullGatewayError(
            403, "SERVICE_NOT_ENABLED", "This service is not enabled for this tenant."
        )

    # Security round 1 MEDIUM 4 - a per-KEY request budget, additive to
    # AC-10-35's own per-IP/401-only bucket above: a resolvable key that is
    # simply narrowly scoped can otherwise probe unlimited out-of-scope ids
    # (403/404/409, never a 401) at zero throttle cost. Counted on EVERY
    # authenticated call, success or business error alike - never merely on
    # a failure, since the exposure is request VOLUME, not credential abuse.
    try:
        throttle.enforce_pull_key(key_id=key_row.id)
    except Throttled as exc:
        raise PullGatewayError(
            429, "TOO_MANY_REQUESTS", "Too many requests for this key. Try again shortly."
        ).with_retry_after(exc.retry_after_seconds)
    throttle.record_pull_key_request(key_id=key_row.id)

    return key_row

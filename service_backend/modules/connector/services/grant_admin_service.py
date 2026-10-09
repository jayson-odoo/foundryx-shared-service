"""Tenant-admin operations over connector grants + products. Tenant-scoped:
the tenant is the caller's, a foreign id is indistinguishable from a missing one."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings

from .. import registry
from ..models import Grant
from ..repositories.connector_repository import ConnectorRepository
from ..schemas import (
    Activity,
    CallItem,
    EventItem,
    GrantItem,
    GrantPage,
    ProductItem,
    SecretState,
    ToolSummary,
)
from .manifest_service import ManifestService, ManifestUnavailable, visible_tools

STATUSES = ("active", "revoked", "expired")


class NotFound(Exception):
    pass


class GrantAdminService:
    def __init__(self, db: Session, tenant_id: str, tenant_slug: str = ""):
        self.db = db
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.repo = ConnectorRepository(db, tenant_id)

    # --- grants ----------------------------------------------------------------------------
    def _items(self, grants: list[Grant]) -> list[GrantItem]:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        counts = self.repo.calls_since([g.id for g in grants], since)
        names = self.repo.client_names(list({g.client_id for g in grants}))
        return [GrantItem(
            id=g.id, status=g.status, product=g.product, productUserId=g.product_user_id,
            userName=g.name, userEmail=g.email, clientName=names.get(g.client_id),
            grantedAt=g.created_at, consentedAt=g.consented_at, lastUsedAt=g.last_used_at,
            calls30d=counts.get(g.id, 0), revokedReason=g.revoked_reason) for g in grants]

    def list(self, *, status: Optional[str], product: Optional[str], search: Optional[str],
             page: int, page_size: int) -> GrantPage:
        if status not in STATUSES:
            status = None
        rows, total = self.repo.list_grants(status=status, product=product, search=search,
                                            page=page, page_size=page_size)
        return GrantPage(data=self._items(rows), total=total, page=page)

    def _grant(self, grant_id: str) -> Grant:
        g = self.repo.get_grant(grant_id)
        if g is None:
            raise NotFound()
        return g

    def get(self, grant_id: str) -> GrantItem:
        return self._items([self._grant(grant_id)])[0]

    def activity(self, grant_id: str) -> Activity:
        g = self._grant(grant_id)
        return Activity(
            calls=[CallItem(id=c.id, tool=c.tool, statusCode=c.http_status, rows=c.rows,
                            chars=c.chars, ms=c.duration_ms, truncated=bool(c.truncated),
                            at=c.created_at, status=c.status, errorCode=c.error_code)
                   for c in self.repo.list_calls(g.id)],
            events=[EventItem(id=e.id, type=e.event, at=e.created_at, detail=e.reason)
                    for e in self.repo.list_events(g.id)])

    def revoke(self, grant_id: str, actor_user_id: str) -> None:
        g = self._grant(grant_id)
        if g.status == "active":
            self.repo.revoke_grant(g, reason="admin", event="revoked_by_admin",
                                   actor_user_id=actor_user_id)
            self.db.commit()

    def bulk_revoke(self, ids: list[str], actor_user_id: str) -> int:
        n = 0
        for gid in dict.fromkeys(ids):
            g = self.repo.get_grant(gid)  # foreign / unknown ids are skipped
            if g is not None and g.status == "active":
                self.repo.revoke_grant(g, reason="admin", event="revoked_by_admin",
                                       actor_user_id=actor_user_id)
                n += 1
        self.db.commit()
        return n

    # --- products -----------------------------------------------------------------------------
    def _owned(self) -> list[registry.ProductStatus]:
        return [st for st in registry.all_products().values()
                if (st.product or st.partial) is not None
                and (st.product or st.partial).tenant_slug == self.tenant_slug]

    def _view(self, st: registry.ProductStatus) -> ProductItem:
        p = st.product or st.partial
        assert p is not None
        cache = self.repo.get_manifest(p.key)
        tools = visible_tools(cache.manifest_json if cache else None)
        return ProductItem(
            key=p.key, displayName=p.display_name,
            mcpUrl=f"{settings.public_base_url.rstrip('/')}/mcp/{p.key}",
            consentUrl=p.consent_url, apiBase=p.api_base_url,
            manifestVersion=cache.version if cache else None, toolCount=len(tools),
            tools=[ToolSummary(name=t["name"], method=t["http"]["method"].upper(),
                               path=t["http"]["path_template"]) for t in tools],
            fetchedAt=cache.fetched_at if cache else None,
            stale=bool(cache and cache.last_error), lastError=cache.last_error if cache else None,
            secrets=SecretState(ssToProduct="set" if p.ss_to_product_secret else "missing",
                                productToSs="set" if p.product_to_ss_secret else "missing"),
            status=st.status)

    def products(self) -> list[ProductItem]:
        return [self._view(st) for st in self._owned()]

    def refresh_manifest(self, key: str) -> ProductItem:
        st = next((s for s in self._owned() if s.key == key), None)
        if st is None or st.product is None:
            raise NotFound()
        try:
            ManifestService(self.db, self.tenant_id, st.product).get(force=True)
        except ManifestUnavailable:
            pass  # reported through stale/lastError; last good keeps serving
        return self._view(st)

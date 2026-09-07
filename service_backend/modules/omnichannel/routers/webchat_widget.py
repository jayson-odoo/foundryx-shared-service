"""Public loader script route (plan 34 / A7b S1, D-A7B-3/D-A7B-12/AC-WEB-20).

Mounted `"public": true` (manifest prefix `/omnichannel/widget`) - like the
Meta webhook/media routes, this endpoint has no authenticated user to resolve
a tenant from, so it re-applies its own module-active + tenant-lifecycle
checks (mirrors `InboundService.process_payload`'s "the webhook router is
mounted public - re-apply the module-active check here" note).

Serves ONE static, hand-written JS file (`widget/loader.js`) with exactly two
plain string substitutions - no Jinja/eval, no per-request template render.
The response is origin-agnostic and cacheable (D-A7B-12): all real per-tenant
configuration lives behind the (uncacheable) session endpoint slice S2 adds.
"""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository

from ..models import Channel

router = APIRouter()

MODULE_NAME = "omnichannel"
_LOADER_PATH = Path(__file__).resolve().parent.parent / "widget" / "loader.js"
_LOADER_TEMPLATE = _LOADER_PATH.read_text(encoding="utf-8")


def _uniform_404() -> HTTPException:
    """AC-WEB-21 - byte-identical for all five failure modes: unknown key,
    trashed channel, inactive channel, module not ACTIVE, tenant cannot sign
    in. Enumeration must learn nothing from the response."""
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


def _resolve_live_channel(db: Session, widget_key: str) -> Channel:
    """GLOBAL lookup by widget_key (unauthenticated, no tenant context yet) -
    mirrors `external_account_id`'s design (migration 0017/0019): the key
    carries its own service-wide PARTIAL UNIQUE index over live rows, so this
    can only ever resolve the ONE channel that legitimately owns it, never a
    different tenant's."""
    channel = (
        db.query(Channel)
        .filter(
            Channel.widget_key == widget_key,
            Channel.channel_type == "WEBCHAT",
            Channel.is_trashed.is_(False),
        )
        .first()
    )
    if channel is None or not channel.is_active:
        raise _uniform_404()
    if not ModuleRepository(db).is_active(channel.tenant_id, MODULE_NAME):
        raise _uniform_404()
    tenant = db.query(Tenant).filter(Tenant.id == channel.tenant_id).first()
    if tenant is None or not tenant.signin_allowed:
        raise _uniform_404()
    return channel


@router.get("/{widget_key}.js")
def get_loader(widget_key: str, db: Session = Depends(get_db)) -> Response:
    _resolve_live_channel(db, widget_key)
    body = _LOADER_TEMPLATE.replace("__WIDGET_KEY__", widget_key).replace(
        "__PANEL_ORIGIN__", settings.frontend_url.rstrip("/")
    )
    etag = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={
            # D-A7B-12: cacheable + origin-agnostic - the loader carries no
            # tenant-identifying content, so a shared CDN cache is safe.
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "ETag": etag,
        },
    )

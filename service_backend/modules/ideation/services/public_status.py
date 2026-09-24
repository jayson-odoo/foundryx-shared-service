"""Public idea-status lookup (S5, AC-1601..1604) - the DB query lives HERE,
never in the router (layering hard-fail). ``resolve(token)`` returns ``None``
for every non-servable case - unknown/malformed token, still-draft idea, or a
tenant whose sign-in is blocked (status-engine ``blocks_access``/
``is_archived``, review round 1 nit 9) - so the router can answer a UNIFORM
404 with no enumeration (mirrors ``FormService._resolve_public``).

Lookup is by ``status_token`` alone, across EVERY tenant (the token is the
credential, not a tenant-scoped lookup) - deliberate exception to the "every
repository query is tenant-scoped" rule, matching the analogous public
document-share route.
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.tenant import Tenant

from ..models import Idea
from ..schemas import PublicIdeaStatusOut

# 16-64 chars, URL-safe - matches ``secrets.token_urlsafe(24)`` output shape
# (AC-1603). Anything outside this shape is rejected before ever touching the
# database (also closes off path-traversal-flavoured tokens).
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class PublicIdeaStatusService:
    def __init__(self, db: Session):
        self.db = db

    def resolve(self, token: str) -> Optional[PublicIdeaStatusOut]:
        if not _TOKEN_RE.fullmatch(token or ""):
            return None

        idea = self.db.query(Idea).filter(Idea.status_token == token).first()
        if idea is None:
            return None

        # A tenant whose sign-in is blocked (suspended/archived) never serves
        # a public surface either - the same chokepoint core checks per
        # request (`Tenant.signin_allowed`, e.g. `FormService._resolve_public`).
        tenant = self.db.query(Tenant).filter(Tenant.id == idea.tenant_id).first()
        if tenant is None or not tenant.signin_allowed:
            return None

        status_row = self.db.query(Status).filter(Status.id == idea.status_id).first()
        # A draft (or a row whose status somehow resolved to nothing) never
        # has a public status - uniform 404, same as "unknown token" (AC-1602).
        if status_row is None or status_row.key == "draft":
            return None

        return PublicIdeaStatusOut(
            title=idea.title, status=status_row.label, ideaNumber=idea.idea_number
        )

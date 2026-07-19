"""Embed-connection admin router (PLAN-ideation-embed-sso §7, AC-E-5/12).

Gated (NOT public): every endpoint requires ``ideation.triage.manage`` (reused —
no new permission / grant sweep) AND the ideation module active for the caller's
tenant (injected by the module loader). Registers the host applications allowed
to embed THIS tenant's Ideas workspace.

The ``signing_secret`` is WRITE-ONLY — it is accepted on create but NEVER returned
(list/create responses omit it, only reporting ``has_secret``). Both sides must
hold the same ``connection_id`` + ``signing_secret``; the host (sorento) stores
its copy in the DEFAULT ``RespondWorkspace`` config."""
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..models import EmbedConnection
from ..services.embed import upsert_connection

router = APIRouter()

_MANAGE = require_permission("ideation.triage.manage")


class EmbedConnectionCreate(BaseModel):
    connection_id: str = Field(..., min_length=1)
    signing_secret: str = Field(..., min_length=8)
    allowed_origins: List[str] = Field(default_factory=list)
    product_id: Optional[str] = None
    is_active: bool = True


class EmbedConnectionOut(BaseModel):
    connection_id: str
    tenant_id: str
    allowed_origins: List[str]
    product_id: Optional[str]
    is_active: bool
    has_secret: bool


def _serialize(row: EmbedConnection) -> EmbedConnectionOut:
    return EmbedConnectionOut(
        connection_id=row.connection_id,
        tenant_id=row.tenant_id,
        allowed_origins=list(row.allowed_origins or []),
        product_id=row.product_id,
        is_active=row.is_active,
        has_secret=bool(row.signing_secret_ciphertext),
    )


@router.get("", response_model=List[EmbedConnectionOut])
def list_embed_connections(
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> List[EmbedConnectionOut]:
    rows = (
        db.query(EmbedConnection)
        .filter(EmbedConnection.tenant_id == current_user.tenant_id)
        .order_by(EmbedConnection.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


@router.post("", response_model=EmbedConnectionOut, status_code=201)
def create_embed_connection(
    body: EmbedConnectionCreate,
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConnectionOut:
    """Register (or re-save) an embed connection for the caller's tenant. The
    signing secret is Fernet-encrypted at rest and never echoed back."""
    row = upsert_connection(
        db,
        connection_id=body.connection_id,
        tenant_id=current_user.tenant_id,
        signing_secret=body.signing_secret,
        allowed_origins=body.allowed_origins,
        product_id=body.product_id,
        is_active=body.is_active,
    )
    return _serialize(row)

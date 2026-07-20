"""Embed-connection admin router (PLAN-ideation-embed-sso §7, AC-E-5/12).

Gated (NOT public): every endpoint requires ``ideation.triage.manage`` (reused —
no new permission / grant sweep) AND the ideation module active for the caller's
tenant (injected by the module loader). Registers the host applications allowed
to embed THIS tenant's Ideas workspace.

The ``signing_secret`` is WRITE-ONLY — it is accepted on create/rotate but NEVER
returned (list/create/rotate responses omit it, only reporting ``has_secret``).
The admin (which supplies the plaintext) is the only side that reveals it, once,
client-side — so the same value can be pasted into the host's (sorento's) embed
config. Both sides must hold the same ``connection_id`` + ``signing_secret``.

Beyond list + create (idempotent upsert), the router supports the lifecycle the
admin UI drives without ever re-supplying the secret: PATCH (enable/disable,
re-scope, edit the origin allow-list), rotate (new secret only), and hard delete.
All endpoints are tenant-scoped — a connection in another tenant is a 404.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..models import EmbedConnection
from ..services.embed import (
    delete_connection,
    rotate_secret,
    update_connection_fields,
    upsert_connection,
)

router = APIRouter()

_MANAGE = require_permission("ideation.triage.manage")


class EmbedConnectionCreate(BaseModel):
    connection_id: str = Field(..., min_length=1)
    signing_secret: str = Field(..., min_length=8)
    allowed_origins: List[str] = Field(default_factory=list)
    product_id: Optional[str] = None
    is_active: bool = True


class EmbedConnectionPatch(BaseModel):
    """Partial update of the non-secret fields. Only the fields supplied are
    written (``model_fields_set`` distinguishes "clear scope" from "unchanged")."""

    allowed_origins: Optional[List[str]] = None
    product_id: Optional[str] = None
    is_active: Optional[bool] = None


class EmbedConnectionRotate(BaseModel):
    signing_secret: str = Field(..., min_length=8)


class EmbedConnectionOut(BaseModel):
    connection_id: str
    tenant_id: str
    allowed_origins: List[str]
    product_id: Optional[str]
    is_active: bool
    has_secret: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _serialize(row: EmbedConnection) -> EmbedConnectionOut:
    return EmbedConnectionOut(
        connection_id=row.connection_id,
        tenant_id=row.tenant_id,
        allowed_origins=list(row.allowed_origins or []),
        product_id=row.product_id,
        is_active=row.is_active,
        has_secret=bool(row.signing_secret_ciphertext),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
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


@router.patch("/{connection_id}", response_model=EmbedConnectionOut)
def update_embed_connection(
    connection_id: str,
    body: EmbedConnectionPatch,
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConnectionOut:
    """Enable/disable, re-scope, or edit the origin allow-list WITHOUT re-supplying
    the secret. 404 when the connection is not in the caller's tenant."""
    supplied = body.model_dump(exclude_unset=True)
    row = update_connection_fields(
        db,
        connection_id=connection_id,
        tenant_id=current_user.tenant_id,
        **supplied,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Embed connection not found.")
    return _serialize(row)


@router.post("/{connection_id}/rotate", response_model=EmbedConnectionOut)
def rotate_embed_connection_secret(
    connection_id: str,
    body: EmbedConnectionRotate,
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConnectionOut:
    """Rotate the signing secret (new secret Fernet-encrypted at rest, never
    returned — the admin reveals its own copy once). Invalidates every assertion
    signed with the old secret. 404 when not in the caller's tenant."""
    row = rotate_secret(
        db,
        connection_id=connection_id,
        tenant_id=current_user.tenant_id,
        signing_secret=body.signing_secret,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Embed connection not found.")
    return _serialize(row)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_embed_connection(
    connection_id: str,
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an embed connection (off-boarding). 404 when not in the caller's
    tenant. Any live embed token for it stops resolving on its next request."""
    ok = delete_connection(
        db, connection_id=connection_id, tenant_id=current_user.tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Embed connection not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

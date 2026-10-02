"""Build write-back key management (``/ideation/build-keys``) - session-authed,
gated by ``ideation.business_requirements.send_to_build``. HTTP + Pydantic only;
the plaintext is returned once, on mint."""
from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import BuildKeyMintIn, BuildKeyMintOut, BuildKeyOut
from ..services.build_keys import BuildKeyService

router = APIRouter()

_PERM = "ideation.business_requirements.send_to_build"


@router.post("", response_model=BuildKeyMintOut, status_code=status.HTTP_201_CREATED)
def mint_build_key(
    body: BuildKeyMintIn,
    current_user: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> BuildKeyMintOut:
    row, plaintext = BuildKeyService(db).mint(
        current_user.tenant_id, body.name, created_by=current_user.id
    )
    return BuildKeyMintOut(
        id=row.id,
        name=row.name,
        keyPrefix=row.key_prefix,
        createdAt=row.created_at,
        lastUsedAt=row.last_used_at,
        plaintext=plaintext,
    )


@router.get("", response_model=List[BuildKeyOut])
def list_build_keys(
    current_user: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> List[BuildKeyOut]:
    return [
        BuildKeyOut(
            id=r.id,
            name=r.name,
            keyPrefix=r.key_prefix,
            createdAt=r.created_at,
            lastUsedAt=r.last_used_at,
        )
        for r in BuildKeyService(db).list_for_tenant(current_user.tenant_id)
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_build_key(
    key_id: str,
    current_user: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> Response:
    BuildKeyService(db).revoke(key_id, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

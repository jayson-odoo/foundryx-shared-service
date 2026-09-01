"""Business Requirement router (Phase B-i slice 2, AC-BI-15..19) - gated by
``require_module("ideation")`` (injected by the loader) + the relevant
``ideation.business_requirements.*`` permission.

HTTP-only (no DB/SQL here - the hard-fail rule): every read/write goes through
``BusinessRequirementService``. Reads/writes ride ``.read`` / ``.manage``; the
lifecycle promote gate (S4) rides a SEPARATE ``.promote`` (AC-BI-19).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    BrLinkIdeasIn,
    BrStatusIn,
    BrTemplateVersionOut,
    BusinessRequirementCreateIn,
    BusinessRequirementDetailOut,
    BusinessRequirementOut,
    BusinessRequirementUpdateIn,
    IdeaOut,
)
from ..services.business_requirements import BusinessRequirementService

router = APIRouter()


@router.get("", response_model=List[BusinessRequirementOut])
def list_business_requirements(
    search: Optional[str] = Query(None),
    filter: str = Query("active", pattern="^(active|archived|all)$"),
    product_id: Optional[str] = Query(None, alias="productId"),
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
) -> List[BusinessRequirementOut]:
    """All BRs for the tenant, newest first. ``search`` matches the title;
    ``filter`` selects active / archived / all; optional ``productId`` scopes to
    a single product. Always tenant-scoped."""
    return BusinessRequirementService(db).list(
        current_user.tenant_id, search=search, filter=filter, product_id=product_id
    )


@router.post(
    "", response_model=BusinessRequirementDetailOut, status_code=status.HTTP_201_CREATED
)
def create_business_requirement(
    body: BusinessRequirementCreateIn,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> BusinessRequirementDetailOut:
    """Create a ``draft`` BR that stamps the active template version and
    validates ``answers`` against it (AC-BI-16)."""
    return BusinessRequirementService(db).create(
        current_user.tenant_id,
        product_id=body.productId,
        title=body.title,
        answers=body.answers,
        idea_ids=body.ideaIds,
        actor=current_user,
    )


# Registered BEFORE /{br_id} so the literal path wins the match (mirrors the
# console's tenant status-graph shim).
@router.get("/status-graph")
def br_status_graph(
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
):
    """The BR entity's status graph for the detail form's action registry
    (AC-BI-34) - gated by ``ideation.business_requirements.read`` so promote/
    lifecycle buttons never depend on the user also holding ``statuses.read``.
    Delegates to the core status-graph reader (the ``.promote`` boundary is the
    server-side gate on the ``br-tr-promote`` edge)."""
    from app.api.v1.statuses import get_status_graph

    from ..services.statuses import BR_ENTITY

    # Keyword args - get_status_graph has a ``scope_id`` param between
    # entity_type and current_user (scoped machines), so a positional call would
    # misplace current_user.
    return get_status_graph(
        entity_type=BR_ENTITY, current_user=current_user, db=db
    )


@router.get("/{br_id}", response_model=BusinessRequirementDetailOut)
def get_business_requirement(
    br_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
) -> BusinessRequirementDetailOut:
    """One BR by id - answers + the STAMPED template doc (for the renderer)."""
    return BusinessRequirementService(db).get(current_user.tenant_id, br_id)


@router.patch("/{br_id}", response_model=BusinessRequirementDetailOut)
def update_business_requirement(
    br_id: str,
    body: BusinessRequirementUpdateIn,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> BusinessRequirementDetailOut:
    """Edit ``title`` / ``answers`` (validated against the STAMPED version)."""
    return BusinessRequirementService(db).update(
        current_user.tenant_id,
        br_id,
        title=body.title,
        answers=body.answers,
        actor=current_user,
    )


@router.get("/{br_id}/ideas", response_model=List[IdeaOut])
def list_br_ideas(
    br_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """The Ideas feeding this BR (lineage, AC-BI-35)."""
    return BusinessRequirementService(db).linked_ideas(current_user.tenant_id, br_id)


@router.post("/{br_id}/ideas", response_model=List[IdeaOut])
def link_br_ideas(
    br_id: str,
    body: BrLinkIdeasIn,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Link ideas to the BR (tenant-scoped + same-product, AC-BI-17)."""
    return BusinessRequirementService(db).link_ideas(
        current_user.tenant_id, br_id, body.ideaIds
    )


@router.delete("/{br_id}/ideas/{idea_id}", response_model=List[IdeaOut])
def unlink_br_idea(
    br_id: str,
    idea_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Unlink one idea from the BR."""
    return BusinessRequirementService(db).unlink_idea(
        current_user.tenant_id, br_id, idea_id
    )


@router.get("/{br_id}/versions", response_model=List[BrTemplateVersionOut])
def list_br_versions(
    br_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
) -> List[BrTemplateVersionOut]:
    """The BR's template version history (Versions tab); flags the stamped one."""
    return BusinessRequirementService(db).template_versions(
        current_user.tenant_id, br_id
    )


@router.post("/{br_id}/status", response_model=BusinessRequirementDetailOut)
def set_br_status(
    br_id: str,
    body: BrStatusIn,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> BusinessRequirementDetailOut:
    """Move the BR to a lifecycle status by key (server-authoritative)."""
    return BusinessRequirementService(db).set_status(
        current_user.tenant_id, br_id, body.status, actor=current_user
    )


@router.delete("/{br_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business_requirement(
    br_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.manage")
    ),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a BR (and its idea links)."""
    BusinessRequirementService(db).delete(current_user.tenant_id, br_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

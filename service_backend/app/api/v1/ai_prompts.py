"""AI prompt registry routes (Meetings S4, R4/R5). Thin: validate, delegate to
`app.services.ai_prompt_registry`, shape HTTP. ALL routes are operator-only -
`require_platform_permission` = permission key AND platform-tenant membership,
same double lock as `app/api/v1/platform_tenants.py`.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_platform_permission
from app.models.user import User
from app.schemas.ai_prompt import (
    AiPromptDetailOut,
    AiPromptSummaryOut,
    AiPromptVersionOut,
    CreatePromptVersionRequest,
    PublishPromptVersionRequest,
)
from app.services import ai_prompt_registry as registry

router = APIRouter()

PERMISSION = "ai_prompts.manage"


@router.get("", response_model=List[AiPromptSummaryOut])
def list_prompts(
    current_user: User = Depends(require_platform_permission(PERMISSION)),
    db: Session = Depends(get_db),
) -> List[AiPromptSummaryOut]:
    return [AiPromptSummaryOut(**row) for row in registry.list_prompts(db)]


@router.get("/{name}", response_model=AiPromptDetailOut)
def get_prompt(
    name: str,
    current_user: User = Depends(require_platform_permission(PERMISSION)),
    db: Session = Depends(get_db),
) -> AiPromptDetailOut:
    try:
        detail = registry.get_prompt_detail(db, name)
    except registry.PromptNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt '{name}' not found.")
    return AiPromptDetailOut(**detail)


@router.post("/{name}/versions", response_model=AiPromptVersionOut, status_code=status.HTTP_201_CREATED)
def create_version(
    name: str,
    payload: CreatePromptVersionRequest,
    current_user: User = Depends(require_platform_permission(PERMISSION)),
    db: Session = Depends(get_db),
) -> AiPromptVersionOut:
    try:
        created = registry.save_version(
            db,
            name,
            template=payload.template,
            commit_message=payload.commitMessage,
            user_id=current_user.id,
        )
    except registry.PromptNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt '{name}' not found.")
    except registry.PromptValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)
    return AiPromptVersionOut(**created)


@router.post("/{name}/publish", response_model=AiPromptDetailOut)
def publish_version(
    name: str,
    payload: PublishPromptVersionRequest,
    current_user: User = Depends(require_platform_permission(PERMISSION)),
    db: Session = Depends(get_db),
) -> AiPromptDetailOut:
    try:
        detail = registry.set_label(
            db, name, label=payload.label, version_id=payload.versionId, user_id=current_user.id
        )
    except registry.PromptNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt '{name}' not found.")
    except registry.InvalidLabel:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown label '{payload.label}'. Allowed: {', '.join(registry.LABELS)}.",
        )
    except registry.PromptVersionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Version not found for prompt '{name}'.")
    return AiPromptDetailOut(**detail)

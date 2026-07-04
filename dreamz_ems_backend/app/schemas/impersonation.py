"""Impersonation schemas (plan 03 §13)."""
from datetime import datetime
from typing import List, Optional


from app.schemas.base import ApiModel


class StartImpersonationRequest(ApiModel):
    targetUserId: str


class ImpersonationTargetUser(ApiModel):
    id: str
    name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    status: str


class ImpersonationSessionResponse(ApiModel):
    sessionId: str
    startedAt: datetime
    targetUser: ImpersonationTargetUser
    # The target's effective permission keys — the frontend gates the UI by these
    # while impersonating (backend still enforces via the header).
    permissions: List[str] = []

"""Small shared RBAC helper for the contact-fields/tags routers (plan 25 S1) -
the first place two of the module's permission keys satisfy the SAME read
gate (`conversations.read` OR `contacts.read`, AC-CDM-28)."""
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.dependencies import effective_permission_keys, get_current_user
from app.models.user import User


def require_any_permission(*keys: str) -> Callable[..., User]:
    """Dependency factory: 403 unless the current (effective) user holds ANY
    of `keys`. Resolves fresh from DB per request, same as `require_permission`."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        held = effective_permission_keys(current_user)
        if not any(key in held for key in keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: one of {', '.join(keys)}",
            )
        return current_user

    return dependency

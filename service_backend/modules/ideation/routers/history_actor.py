"""Who acted, for a feedback item's History tab (lane FEEDBACK-SUBSCRIBE):
the real staff user; while impersonating, on behalf of the impersonated one."""
from fastapi import Request

from app.models.user import User

from ..services.history import HistoryActor, staff_actor


def request_actor(request: Request, current_user: User) -> HistoryActor:
    real = getattr(request.state, "real_user", None)
    real_name = real.name if isinstance(real, User) else None
    return staff_actor(real_name, current_user.name)

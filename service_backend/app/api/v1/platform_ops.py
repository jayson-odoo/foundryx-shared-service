"""Platform ops routes (sprint-5/11 S1, AC-11-86) - operator-only.

A frozen Celery worker must be visible within minutes, not discovered by an
operator hours later (the 2026-09-20/21 incident). Reads the per-queue Redis
liveness stamp (`app/ops_liveness.py`) written by the `ops.ping` beat/worker
pair. No DB access here - this route is a pure Redis read, gated the same
way every other platform-console read is.
"""
from fastapi import APIRouter, Depends

from app.dependencies import require_platform_permission
from app.models.user import User
from app.ops_liveness import KNOWN_QUEUES, queue_status
from app.schemas.ops import QueueLivenessResponse

router = APIRouter()


@router.get("/queues", response_model=QueueLivenessResponse)
def list_queue_liveness(
    # R11: reuses the EXISTING platform-console read permission (grepped
    # `app/permissions/platform_permissions.csv` - `tenants.read` is already
    # the key every other platform-console GET uses); no new CSV row, no
    # grant sweep.
    current_user: User = Depends(require_platform_permission("tenants.read")),
) -> QueueLivenessResponse:
    return QueueLivenessResponse(
        queues=[queue_status(queue) for queue in KNOWN_QUEUES]
    )

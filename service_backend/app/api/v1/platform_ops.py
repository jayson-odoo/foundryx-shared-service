"""Platform ops routes (sprint-5/11 S1, AC-11-86) - operator-only.

A frozen Celery worker must be visible within minutes, not discovered by an
operator hours later (the 2026-09-20/21 incident). Reads the per-queue Redis
liveness stamp (`app/ops_liveness.py`) written by the `ops.ping` beat/worker
pair, plus (review round 1, S2) a live Celery control-plane ping. No DB
access here - the Redis read is pure; the control-plane ping is a
synchronous best-effort broker round-trip (1s timeout), gated the same way
every other platform-console read is.

Per queue: `stale` means "no free slot OR dead" - a worker consuming this
queue has not drained a recent `ops.ping` broker message (it may simply be
busy on a long job, not dead). `alive` is the control plane's OWN answer:
a live `ping()` from a worker whose `active_queues()` names this queue,
independent of the broker-routed stamp above. A dead/unreachable broker
reads `alive: False` for every queue; this route never raises for it.

Covers ONLY the workflow Celery app's queues (`workflow`, `jobs` -
`app.ops_liveness.KNOWN_QUEUES`). The omnichannel app's `omni` queue, and any
future `stt`/`bots` app, are separate Celery apps with no liveness signal
wired here yet.
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

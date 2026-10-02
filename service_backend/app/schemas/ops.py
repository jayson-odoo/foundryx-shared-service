"""Platform ops schemas (sprint-5/11 S1, AC-11-86) - per-queue Celery worker
liveness. Wire = camelCase (`ApiModel` for the Z-suffixed `lastSeen`).

Review round 1 (S2): python attrs are snake_case per house convention
(`validation_alias`/`serialization_alias`), constructed straight from
`app.ops_liveness.queue_status()`'s own camelCase dict via `model_validate`
(pydantic reads `validation_alias` against dict keys same as any other
input)."""
from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.base import ApiModel


class QueueLivenessItem(ApiModel):
    queue: str
    last_seen: Optional[datetime] = Field(
        default=None, validation_alias="lastSeen", serialization_alias="lastSeen"
    )
    stale: bool
    alive: bool


class QueueLivenessResponse(ApiModel):
    queues: List[QueueLivenessItem]

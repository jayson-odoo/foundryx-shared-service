"""Platform ops schemas (sprint-5/11 S1, AC-11-86) - per-queue Celery worker
liveness. Wire = camelCase (`ApiModel` for the Z-suffixed `lastSeen`)."""
from datetime import datetime
from typing import List, Optional

from app.schemas.base import ApiModel


class QueueLivenessItem(ApiModel):
    queue: str
    lastSeen: Optional[datetime] = None
    stale: bool


class QueueLivenessResponse(ApiModel):
    queues: List[QueueLivenessItem]

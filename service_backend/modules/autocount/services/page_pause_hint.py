"""SS-STOCK-PAGE-PAUSE-CONFIG - the read-only hint under the connection's
"Pause between pages (seconds)" field: "About N pages per run -> about X min
per run", from the last successful run of the connection's heaviest task.

The pause applies to every open-REST task reading through the connection
(``http_source/source.py`` main walk), so the hint follows the task with the
most pages - the one the owner is pacing (today the stock balance pull).
The frontend recomputes X live as the field is edited:
``max(lastRunSeconds - (pages-1)*savedPauseSeconds, 0) + (pages-1)*typed``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..http_source.client import connection_sizing
from ..http_source.gentle import gentle_settings
from ..repositories import EntityConfigRepository, SyncRunRepository

HINT_KIND_PAGE_RUN = "pageRun"


def page_run_hint(db: Session, connection: Any) -> Optional[Dict[str, Any]]:
    """``None`` until a task on this connection has a successful run."""
    config = connection.config_json or {}
    page_size = connection_sizing(config).page_size
    runs = SyncRunRepository(db)
    best: Optional[Dict[str, Any]] = None
    for task in EntityConfigRepository(db).list_http_for_connection(
        connection.tenant_id, connection.id
    ):
        run = runs.last_successful(task.tenant_id, task.company_id, task.entity_type)
        if run is None or not run.rows_scanned:
            continue
        pages = max(1, math.ceil(run.rows_scanned / page_size))
        if best is None or pages > best["pages"]:
            best = {
                "kind": HINT_KIND_PAGE_RUN,
                "pages": pages,
                "lastRunSeconds": round((run.duration_ms or 0) / 1000.0, 1),
                "savedPauseSeconds": gentle_settings(config).page_pause_seconds,
            }
    return best

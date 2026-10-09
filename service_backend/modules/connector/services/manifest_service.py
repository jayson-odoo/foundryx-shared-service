"""Product manifest cache (15 min TTL, last-good on failure). Tenant-scoped."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from .. import registry
from ..repositories.connector_repository import ConnectorRepository
from . import product_client

MANIFEST_PATH = "/api/v1/connector/manifest"


class ManifestUnavailable(Exception):
    pass


def is_visible_tool(tool: Any) -> bool:
    """Read-only only: readOnlyHint true AND destructiveHint not true; shape-checked."""
    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
        return False
    ann = tool.get("annotations")
    if not isinstance(ann, dict) or ann.get("readOnlyHint") is not True or ann.get("destructiveHint") is True:
        return False
    http = tool.get("http")
    return (isinstance(http, dict) and isinstance(http.get("method"), str)
            and isinstance(http.get("path_template"), str)
            and isinstance(tool.get("input_schema"), dict))


def visible_tools(manifest: Optional[dict]) -> list[dict]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tools"), list):
        return []
    return [t for t in manifest["tools"] if is_visible_tool(t)]


class ManifestService:
    def __init__(self, db: Session, tenant_id: str, product: registry.Product):
        self.db = db
        self.product = product
        self.repo = ConnectorRepository(db, tenant_id)

    def cached(self):
        return self.repo.get_manifest(self.product.key)

    def get(self, *, force: bool = False) -> dict:
        row = self.cached()
        now = datetime.now(timezone.utc)
        if (not force and row is not None and row.manifest_json and row.fetched_at is not None
                and now - row.fetched_at < timedelta(seconds=registry.manifest_ttl_seconds())):
            return row.manifest_json
        try:
            return self._fetch(row, now)
        except ManifestUnavailable:
            if row is not None and row.manifest_json:
                return row.manifest_json  # last good keeps serving
            raise

    def _fetch(self, row, now: datetime) -> dict:
        error: Optional[str] = None
        data: Any = None
        try:
            resp = product_client.send(
                self.product, method="GET", raw_path=MANIFEST_PATH, query="", body=b"",
                sub="", grant_id="", consented_at=0, tool="")
            if resp.status_code != 200:
                error = f"HTTP {resp.status_code}"
            else:
                data = resp.json()
                if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
                    error, data = "invalid manifest", None
        except httpx.HTTPError as exc:
            error = type(exc).__name__
        except ValueError:
            error = "invalid manifest"
        if row is None:
            row = self.repo.new_manifest(self.product.key)
        if error is not None:
            row.last_error = error
            self.db.commit()
            raise ManifestUnavailable(error)
        row.manifest_json = data
        row.version = str(data.get("version"))[:128] if data.get("version") is not None else None
        row.fetched_at = now
        row.last_error = None
        self.db.commit()
        return data

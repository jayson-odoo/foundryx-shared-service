"""Dashboard store (contract 3.2-3.7, 6): save / get / list / share / delete / versions.

Ownership: only the owner saves, shares, deletes or builds on a dashboard; a recipient reads; anyone
else (and any other tenant or product) gets ``not_found``. No method here calls the LLM."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .. import schemas
from ..gateway_auth import DashKey
from ..models import DashDashboard, DashIdempotency, DashVersion
from ..repositories.dashboard_repository import DashboardRepository
from ..spec import validate_spec
from .errors import DashError, not_found, not_owner, spec_invalid

IDEMPOTENCY_WINDOW = timedelta(hours=24)
MAX_SHARES = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canon(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"))


class DashboardStore:
    def __init__(self, db: Session, key: DashKey):
        self.db = db
        self.key = key
        self.repo = DashboardRepository(db, key.tenant_id, key.product)

    # -- access --------------------------------------------------------------------------------------
    def readable(self, dashboard_id: str, actor_ref: str) -> DashDashboard:
        """Owner or recipient, else not_found (never 403: existence does not leak)."""
        row = self.repo.get(dashboard_id)
        if row is None or not (row.owner_ref == actor_ref or self.repo.is_recipient(row.id, actor_ref)):
            raise not_found()
        return row

    def owned(self, dashboard_id: str, actor_ref: str) -> DashDashboard:
        row = self.readable(dashboard_id, actor_ref)
        if row.owner_ref != actor_ref:
            raise not_owner()
        return row

    # -- shapes --------------------------------------------------------------------------------------
    def _out(self, row: DashDashboard, actor_ref: str, *, with_problems: bool = False) -> Dict[str, Any]:
        mine = row.owner_ref == actor_ref
        data = {
            "id": row.id, "name": row.name, "owner_ref": row.owner_ref, "mine": mine,
            "shared_with": [{"user_ref": r} for r in self.repo.share_refs(row.id)] if mine else [],
            "spec": row.spec_json, "version": row.version,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
        problems = validate_spec(row.spec_json) if with_problems else []
        model = schemas.DashboardWithProblemsOut(**data, spec_problems=problems) if problems else schemas.DashboardOut(**data)
        return model.model_dump(mode="json")

    # -- reads ---------------------------------------------------------------------------------------
    def get(self, actor_ref: str, dashboard_id: str) -> Dict[str, Any]:
        return self._out(self.readable(dashboard_id, actor_ref), actor_ref, with_problems=True)

    def list(self, actor_ref: str, scope: str, q: Optional[str], sort: str, direction: str,
             page: int, limit: int) -> Dict[str, Any]:
        rows, total = self.repo.list(actor_ref, scope, q, sort, direction, page, limit)
        counts = self.repo.share_counts([r.id for r in rows])
        items = [
            schemas.DashboardListItem(
                id=r.id, name=r.name, owner_ref=r.owner_ref, mine=r.owner_ref == actor_ref,
                shared=counts.get(r.id, 0) > 0, shared_count=counts.get(r.id, 0),
                updated_at=r.updated_at, version=r.version)
            for r in rows
        ]
        return schemas.DashboardList(items=items, total=total, page=page, limit=limit).model_dump(mode="json")

    def versions(self, actor_ref: str, dashboard_id: str, page: int, limit: int) -> Dict[str, Any]:
        row = self.readable(dashboard_id, actor_ref)
        rows, total = self.repo.versions(row.id, page, limit)
        items = [
            schemas.VersionItem(version=v.version, action=v.action, actor_ref=v.actor_ref, at=v.created_at,
                                changes=[schemas.VersionChange(**c) for c in (v.changes_json or [])])
            for v in rows
        ]
        return schemas.VersionList(items=items, total=total, page=page, limit=limit).model_dump(mode="json")

    # -- writes --------------------------------------------------------------------------------------
    def save(self, body: schemas.SaveRequest) -> Dict[str, Any]:
        actor = body.actor_ref
        replay = self.repo.get_idempotent(self.key.key_id, actor, body.idempotency_key, _now() - IDEMPOTENCY_WINDOW)
        if replay is not None:
            return replay.response_json
        row: Optional[DashDashboard] = None
        if body.dashboard_id is not None:
            row = self.owned(body.dashboard_id, actor)
            if body.base_version != row.version:
                raise DashError(409, "version_conflict", "This dashboard was changed by someone else. Reload it first.",
                                {"current_version": row.version})
        problems = validate_spec(body.spec)
        if problems:
            raise spec_invalid(problems)

        if row is None:
            row = self.repo.add(DashDashboard(owner_ref=actor, name=body.name, spec_json=body.spec, version=1))
            self.repo.add_version(DashVersion(dashboard_id=row.id, version=1, action="created", actor_ref=actor,
                                              changes_json=[]))
        else:
            old_tiles = len((row.spec_json or {}).get("tiles") or [])
            spec_changed = _canon(row.spec_json) != _canon(body.spec)
            name_changed = row.name != body.name
            changes: List[Dict[str, Any]] = []
            if name_changed and not spec_changed:
                action = "renamed"
            else:
                action = "saved"
                changes.append({"field": "charts", "old": old_tiles, "new": len(body.spec.get("tiles") or [])})
            if name_changed:
                changes.append({"field": "name", "old": row.name, "new": body.name})
            row.name, row.spec_json = body.name, body.spec
            row.version += 1
            row.updated_at = _now()
            self.repo.add_version(DashVersion(dashboard_id=row.id, version=row.version, action=action,
                                              actor_ref=actor, changes_json=changes))
        out = self._out(row, actor)
        self.repo.add_idempotent(DashIdempotency(key_id=self.key.key_id, actor_ref=actor,
                                                 idempotency_key=body.idempotency_key, response_json=out))
        self.db.commit()
        return out

    def share(self, dashboard_id: str, body: schemas.ShareRequest) -> Dict[str, Any]:
        actor = body.actor_ref
        row = self.owned(dashboard_id, actor)
        new_refs: List[str] = []
        for item in body.shared_with:
            if item.user_ref != actor and item.user_ref not in new_refs:
                new_refs.append(item.user_ref)
        old_refs = self.repo.share_refs(row.id)
        self.repo.replace_shares(row.id, new_refs)
        row.version += 1
        row.updated_at = _now()
        self.repo.add_version(DashVersion(dashboard_id=row.id, version=row.version, action="shared", actor_ref=actor,
                                          changes_json=[{"field": "shared_with", "old": old_refs, "new": new_refs}]))
        out = self._out(row, actor)
        self.db.commit()
        return out

    def delete(self, dashboard_id: str, actor_ref: str) -> Dict[str, Any]:
        row = self.owned(dashboard_id, actor_ref)
        self.repo.delete(row)
        self.db.commit()
        return schemas.Deleted(deleted=True).model_dump()

"""Permission repository — catalog reads + idempotent module sync.

The catalog is global (no tenant scope). `sync` is the App-Store mechanism:
upsert the rows a module declares (keyed by `key`) and delete that module's rows
no longer declared — so install/update/uninstall stay clean (plan 03 §4).
"""
from typing import Iterable, List

from sqlalchemy.orm import Session

from app.models.permission import Permission


class PermissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> List[Permission]:
        return self.db.query(Permission).order_by(Permission.module, Permission.resource).all()

    def get_by_keys(self, keys: Iterable[str]) -> List[Permission]:
        key_list = list(keys)
        if not key_list:
            return []
        return self.db.query(Permission).filter(Permission.key.in_(key_list)).all()

    def all_keys(self) -> List[str]:
        return [row.key for row in self.db.query(Permission.key).all()]

    def sync(self, module: str, rows: List[dict]) -> None:
        """Upsert the module's declared permissions; delete its undeclared ones."""
        existing = {p.key: p for p in self.db.query(Permission).filter(Permission.module == module).all()}
        declared_keys = set()

        for row in rows:
            key = f"{row['resource']}.{row['action']}"
            declared_keys.add(key)
            perm = existing.get(key)
            if perm is None:
                self.db.add(
                    Permission(
                        key=key,
                        module=module,
                        resource=row["resource"],
                        resource_label=row["resource_label"],
                        action=row["action"],
                        action_label=row["action_label"],
                        description=row.get("description") or None,
                    )
                )
            else:
                perm.resource = row["resource"]
                perm.resource_label = row["resource_label"]
                perm.action = row["action"]
                perm.action_label = row["action_label"]
                perm.description = row.get("description") or None

        # Drop rows this module no longer declares (grants cascade via FK).
        for key, perm in existing.items():
            if key not in declared_keys:
                self.db.delete(perm)

        self.db.commit()

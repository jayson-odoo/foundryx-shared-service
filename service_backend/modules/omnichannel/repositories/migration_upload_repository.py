"""``migration_uploads`` repository (plan 33 review round 1, finding B2) -
the tenant-scoped receipt `MigrationJobCreate.contactsUploadId`/
`snippetsUploadId` resolve against. Every lookup is tenant- (and optionally
kind-) scoped - NEVER a bare ``get(id)`` (the polymorphic-stored-id house
rule this codebase has been bitten by twice already)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import MigrationUpload


class MigrationUploadRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: Optional[str],
        kind: str,
        storage_key: str,
        row_count: int,
        headers: List[str],
        created_by: Optional[str],
    ) -> MigrationUpload:
        row = MigrationUpload(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=kind,
            storage_key=storage_key,
            row_count=row_count,
            headers_json=headers,
            created_by=created_by,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_for_tenant(
        self, tenant_id: str, upload_id: str, *, kind: Optional[str] = None
    ) -> Optional[MigrationUpload]:
        q = self.db.query(MigrationUpload).filter(
            MigrationUpload.tenant_id == tenant_id, MigrationUpload.id == upload_id
        )
        if kind is not None:
            q = q.filter(MigrationUpload.kind == kind)
        return q.first()

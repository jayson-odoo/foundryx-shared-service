"""Drive persistence (plan sprint-3/04) — pure SQLAlchemy, ALWAYS tenant-scoped.
Every query filters ``tenant_id`` from the authed context, never client input
(multi-tenancy invariant). Repository flushes but does NOT commit — the service
owns the transaction (so it can ``emit_entity_event`` before the commit that
drives the after-commit workflow drain)."""
from typing import List, Optional, Set, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.document import (
    AttachmentType,
    DocumentSettings,
    DownloadJob,
    File,
    FileVersion,
    Folder,
)


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- folders ----

    def get_folder(self, tenant_id: str, folder_id: str) -> Optional[Folder]:
        return (
            self.db.query(Folder)
            .filter(Folder.id == folder_id, Folder.tenant_id == tenant_id)
            .first()
        )

    def child_folders(
        self, tenant_id: str, parent_id: Optional[str], *, deleted: bool = False
    ) -> List[Folder]:
        return (
            self.db.query(Folder)
            .filter(
                Folder.tenant_id == tenant_id,
                Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id,
                Folder.is_deleted.is_(deleted),
            )
            .order_by(func.lower(Folder.name))
            .all()
        )

    def child_files(
        self, tenant_id: str, folder_id: Optional[str], *, deleted: bool = False
    ) -> List[File]:
        return (
            self.db.query(File)
            .filter(
                File.tenant_id == tenant_id,
                File.folder_id.is_(None) if folder_id is None else File.folder_id == folder_id,
                File.is_deleted.is_(deleted),
            )
            .order_by(func.lower(File.name))
            .all()
        )

    def breadcrumb(self, tenant_id: str, folder_id: Optional[str]) -> List[Folder]:
        crumbs: List[Folder] = []
        seen: Set[str] = set()
        cur = self.get_folder(tenant_id, folder_id) if folder_id else None
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            crumbs.insert(0, cur)
            cur = self.get_folder(tenant_id, cur.parent_id) if cur.parent_id else None
        return crumbs

    def subtree_folder_ids(self, tenant_id: str, root_id: str) -> Set[str]:
        """All descendant folder ids (inclusive) — for cascade + cycle guard."""
        out: Set[str] = {root_id}
        frontier = [root_id]
        while frontier:
            children = (
                self.db.query(Folder.id)
                .filter(Folder.tenant_id == tenant_id, Folder.parent_id.in_(frontier))
                .all()
            )
            frontier = [c.id for c in children if c.id not in out]
            out.update(frontier)
        return out

    def folder_counts(self, tenant_id: str, folder_id: str) -> Tuple[int, int]:
        folders = (
            self.db.query(func.count(Folder.id))
            .filter(
                Folder.tenant_id == tenant_id,
                Folder.parent_id == folder_id,
                Folder.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )
        files = (
            self.db.query(func.count(File.id))
            .filter(
                File.tenant_id == tenant_id,
                File.folder_id == folder_id,
                File.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )
        return folders, files

    def folder_name_taken(
        self, tenant_id: str, parent_id: Optional[str], name: str, exclude_id: Optional[str] = None
    ) -> bool:
        q = self.db.query(Folder.id).filter(
            Folder.tenant_id == tenant_id,
            Folder.is_deleted.is_(False),
            func.lower(Folder.name) == name.lower(),
            Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id,
        )
        if exclude_id:
            q = q.filter(Folder.id != exclude_id)
        return self.db.query(q.exists()).scalar()

    def add_folder(self, folder: Folder) -> Folder:
        self.db.add(folder)
        self.db.flush()
        return folder

    # ---- files + versions ----

    def get_file(self, tenant_id: str, file_id: str) -> Optional[File]:
        return (
            self.db.query(File)
            .filter(File.id == file_id, File.tenant_id == tenant_id)
            .first()
        )

    def file_by_name(
        self, tenant_id: str, folder_id: Optional[str], name: str
    ) -> Optional[File]:
        return (
            self.db.query(File)
            .filter(
                File.tenant_id == tenant_id,
                File.is_deleted.is_(False),
                func.lower(File.name) == name.lower(),
                File.folder_id.is_(None) if folder_id is None else File.folder_id == folder_id,
            )
            .first()
        )

    def versions(self, file_id: str) -> List[FileVersion]:
        return (
            self.db.query(FileVersion)
            .filter(FileVersion.file_id == file_id)
            .order_by(FileVersion.ordinal.desc())
            .all()
        )

    def current_version(self, file: File) -> Optional[FileVersion]:
        if file.current_version_id is None:
            return None
        return (
            self.db.query(FileVersion)
            .filter(
                FileVersion.id == file.current_version_id,
                FileVersion.file_id == file.id,
            )
            .first()
        )

    def add_file(self, file: File) -> File:
        self.db.add(file)
        self.db.flush()
        return file

    def add_version(self, version: FileVersion) -> FileVersion:
        self.db.add(version)
        self.db.flush()
        return version

    def used_bytes(self, tenant_id: str) -> int:
        # Quota basis = "sum of non-purged version bytes" (plan D12). Trashed
        # files still occupy storage (blobs are dropped only on PURGE, which
        # also deletes the File row) — so count EVERY surviving file's versions,
        # is_deleted or not, else trash-then-upload would bypass the quota.
        return (
            self.db.query(func.coalesce(func.sum(FileVersion.size_bytes), 0))
            .select_from(FileVersion)
            .join(File, File.id == FileVersion.file_id)
            .filter(File.tenant_id == tenant_id)
            .scalar()
            or 0
        )

    # ---- trash ----

    def trashed_folders(self, tenant_id: str) -> List[Folder]:
        return (
            self.db.query(Folder)
            .filter(Folder.tenant_id == tenant_id, Folder.is_deleted.is_(True))
            .order_by(func.lower(Folder.name))
            .all()
        )

    def trashed_files(self, tenant_id: str) -> List[File]:
        return (
            self.db.query(File)
            .filter(File.tenant_id == tenant_id, File.is_deleted.is_(True))
            .order_by(func.lower(File.name))
            .all()
        )

    def files_in_folders(self, tenant_id: str, folder_ids: List[str]) -> List[File]:
        if not folder_ids:
            return []
        return (
            self.db.query(File)
            .filter(File.tenant_id == tenant_id, File.folder_id.in_(folder_ids))
            .all()
        )

    def all_versions_for_files(self, file_ids: List[str]) -> List[FileVersion]:
        if not file_ids:
            return []
        return (
            self.db.query(FileVersion).filter(FileVersion.file_id.in_(file_ids)).all()
        )

    # ---- attachment types ----

    def paginate_types(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
    ) -> Tuple[List[AttachmentType], int]:
        query = self.db.query(AttachmentType).filter(
            AttachmentType.tenant_id == tenant_id
        )
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    AttachmentType.name.ilike(like),
                    AttachmentType.description.ilike(like),
                )
            )
        total = query.count()
        sort_map = {
            "name": AttachmentType.name,
            "maxMb": AttachmentType.max_mb,
            "createdAt": AttachmentType.created_at,
        }
        col = sort_map.get(sort_by or "name", AttachmentType.name)
        query = query.order_by(col.desc() if sort_dir == "desc" else col.asc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get_type(self, tenant_id: str, type_id: str) -> Optional[AttachmentType]:
        return (
            self.db.query(AttachmentType)
            .filter(
                AttachmentType.id == type_id, AttachmentType.tenant_id == tenant_id
            )
            .first()
        )

    def type_file_count(self, tenant_id: str, type_id: str) -> int:
        return (
            self.db.query(func.count(File.id))
            .filter(
                File.tenant_id == tenant_id,
                File.attachment_type_id == type_id,
                File.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )

    def add_type(self, row: AttachmentType) -> AttachmentType:
        self.db.add(row)
        self.db.flush()
        return row

    # ---- settings ----

    def get_settings(self, tenant_id: str) -> Optional[DocumentSettings]:
        return (
            self.db.query(DocumentSettings)
            .filter(DocumentSettings.tenant_id == tenant_id)
            .first()
        )

    def add_settings(self, row: DocumentSettings) -> DocumentSettings:
        self.db.add(row)
        self.db.flush()
        return row

    # ---- download jobs ----

    def add_job(self, job: DownloadJob) -> DownloadJob:
        self.db.add(job)
        self.db.flush()
        return job

    def get_job(self, tenant_id: str, user_id: str, job_id: str) -> Optional[DownloadJob]:
        return (
            self.db.query(DownloadJob)
            .filter(
                DownloadJob.id == job_id,
                DownloadJob.tenant_id == tenant_id,
                DownloadJob.user_id == user_id,
            )
            .first()
        )

    def list_jobs(self, tenant_id: str, user_id: str, limit: int = 50) -> List[DownloadJob]:
        return (
            self.db.query(DownloadJob)
            .filter(DownloadJob.tenant_id == tenant_id, DownloadJob.user_id == user_id)
            .order_by(DownloadJob.created_at.desc())
            .limit(limit)
            .all()
        )

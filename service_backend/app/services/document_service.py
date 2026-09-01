"""Drive business logic (plan sprint-3/04) - Router → THIS → Repository.

Owns the Drive lifecycle: folder/file CRUD, the upload pipeline (sniff hard
floor → type/size policy → quota → name-collision → version append → storage),
soft-delete + Trash + restore + purge, the async ZIP job, attachment types and
the per-tenant settings. Storage bytes ride ``storage_for_tenant`` with the key
``documents/{file_id}/{version_id}`` (flat by id, so rename/move never touch a
blob). A ``file`` workflow event is emitted on upload/move/rename/delete,
failure-isolated, riding the SAME commit (D13).

Errors are SERVICE exceptions the router maps to HTTP (workflow_service
precedent): ``DocumentNotFound`` 404, ``UploadConflict`` 409 {fileName,
existingFileId}, ``QuotaExceeded`` 413, ``UploadRejected`` 415, ``CycleError``
422, ``JobNotReady`` 409.
"""
import io
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.document import (
    DOWNLOAD_FAILED,
    DOWNLOAD_PENDING,
    DOWNLOAD_READY,
    SHARING_VALUES,
    AttachmentType,
    DocumentSettings,
    DownloadJob,
    File,
    FileVersion,
    Folder,
)
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    AttachmentTypeOut,
    Crumb,
    DocumentSettingsOut,
    DownloadJobOut,
    FileOut,
    FileVersionOut,
    FolderListingOut,
    FolderOut,
    TrashListingOut,
)
from app.services.storage import storage_for_tenant
from app.uploads import detect_document_mime
from app.workflow_engine.entity_events import emit_entity_event

MB = 1024 * 1024


# ---- service exceptions ----


class DocumentNotFound(Exception):
    pass


class CycleError(Exception):
    pass


class UploadConflict(Exception):
    def __init__(self, file_name: str, existing_file_id: str):
        super().__init__(file_name)
        self.file_name = file_name
        self.existing_file_id = existing_file_id


class QuotaExceeded(Exception):
    pass


class UploadRejected(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class JobNotReady(Exception):
    pass


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DocumentRepository(db)

    # ---- builders ----

    def _version_out(self, v: FileVersion) -> FileVersionOut:
        return FileVersionOut(
            id=v.id,
            ordinal=v.ordinal,
            size_bytes=v.size_bytes,
            mime=v.mime,
            uploaded_by=v.uploaded_by,
            created_at=v.created_at,
        )

    def _file_out(self, f: File) -> FileOut:
        current = self.repo.current_version(f)
        type_name = None
        if f.attachment_type_id:
            t = self.repo.get_type(f.tenant_id, f.attachment_type_id)
            type_name = t.name if t else None
        return FileOut(
            id=f.id,
            folder_id=f.folder_id,
            name=f.name,
            current_version=self._version_out(current),
            attachment_type_id=f.attachment_type_id,
            attachment_type_name=type_name,
            version_count=len(self.repo.versions(f.id)),
            created_by=f.created_by,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )

    def _folder_out(self, f: Folder, *, with_path: bool = False) -> FolderOut:
        folders, files = self.repo.folder_counts(f.tenant_id, f.id)
        path: List[Crumb] = []
        if with_path and f.parent_id:
            path = [
                Crumb(id=c.id, name=c.name)
                for c in self.repo.breadcrumb(f.tenant_id, f.parent_id)
            ]
        return FolderOut(
            id=f.id,
            parent_id=f.parent_id,
            name=f.name,
            path=path,
            folder_count=folders,
            file_count=files,
            created_by=f.created_by,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )

    # ---- navigation ----

    def list_folder(self, tenant_id: str, folder_id: Optional[str]) -> FolderListingOut:
        folder = None
        if folder_id:
            folder = self.repo.get_folder(tenant_id, folder_id)
            if folder is None or folder.is_deleted:
                raise DocumentNotFound()
        crumbs = [
            Crumb(id=c.id, name=c.name)
            for c in self.repo.breadcrumb(tenant_id, folder_id)
        ]
        return FolderListingOut(
            folder=self._folder_out(folder) if folder else None,
            breadcrumb=crumbs,
            folders=[
                self._folder_out(c)
                for c in self.repo.child_folders(tenant_id, folder_id)
            ],
            files=[self._file_out(c) for c in self.repo.child_files(tenant_id, folder_id)],
        )

    # ---- folder ops ----

    def create_folder(
        self, tenant_id: str, parent_id: Optional[str], name: str, actor: User
    ) -> FolderOut:
        name = (name or "").strip() or "Untitled folder"
        if parent_id and self.repo.get_folder(tenant_id, parent_id) is None:
            raise DocumentNotFound()
        folder = Folder(
            tenant_id=tenant_id, parent_id=parent_id, name=name, created_by=actor.id
        )
        self.repo.add_folder(folder)
        self.db.commit()
        return self._folder_out(folder, with_path=True)

    def rename_folder(self, tenant_id: str, folder_id: str, name: str) -> FolderOut:
        folder = self.repo.get_folder(tenant_id, folder_id)
        if folder is None:
            raise DocumentNotFound()
        folder.name = (name or "").strip() or folder.name
        self.db.commit()
        return self._folder_out(folder, with_path=True)

    def rename_file(self, tenant_id: str, file_id: str, name: str, actor: User) -> FileOut:
        file = self.repo.get_file(tenant_id, file_id)
        if file is None:
            raise DocumentNotFound()
        old = file.name
        file.name = (name or "").strip() or file.name
        if file.name != old:
            emit_entity_event(
                self.db, "file", "updated", file,
                tenant_id=tenant_id, actor=actor,
                changes={"name": {"from": old, "to": file.name}},
            )
        self.db.commit()
        return self._file_out(file)

    def move(
        self,
        tenant_id: str,
        folder_ids: List[str],
        file_ids: List[str],
        target_folder_id: Optional[str],
        actor: User,
    ) -> None:
        if target_folder_id and self.repo.get_folder(tenant_id, target_folder_id) is None:
            raise DocumentNotFound()
        for fid in folder_ids:
            folder = self.repo.get_folder(tenant_id, fid)
            if folder is None:
                continue
            # Cycle guard: can't move a folder into itself or a descendant.
            if target_folder_id and target_folder_id in self.repo.subtree_folder_ids(
                tenant_id, fid
            ):
                raise CycleError()
            folder.parent_id = target_folder_id
        for fid in file_ids:
            file = self.repo.get_file(tenant_id, fid)
            if file is None:
                continue
            file.folder_id = target_folder_id
            emit_entity_event(
                self.db, "file", "updated", file,
                tenant_id=tenant_id, actor=actor,
                changes={"folderId": {"from": None, "to": target_folder_id}},
            )
        self.db.commit()

    # ---- delete / trash ----

    def delete(
        self, tenant_id: str, folder_ids: List[str], file_ids: List[str], actor: User
    ) -> None:
        now = datetime.now(timezone.utc)
        for fid in folder_ids:
            folder = self.repo.get_folder(tenant_id, fid)
            if folder is None:
                continue
            subtree = self.repo.subtree_folder_ids(tenant_id, fid)
            for sub_id in subtree:
                sub = self.repo.get_folder(tenant_id, sub_id)
                if sub:
                    sub.is_deleted = True
                    sub.deleted_at = now
                    sub.deleted_by = actor.id
            for file in self.repo.files_in_folders(tenant_id, list(subtree)):
                file.is_deleted = True
                file.deleted_at = now
                file.deleted_by = actor.id
        for fid in file_ids:
            file = self.repo.get_file(tenant_id, fid)
            if file is None or file.is_deleted:
                continue
            file.is_deleted = True
            file.deleted_at = now
            file.deleted_by = actor.id
            emit_entity_event(
                self.db, "file", "deleted", file, tenant_id=tenant_id, actor=actor
            )
        self.db.commit()

    def list_trash(self, tenant_id: str) -> TrashListingOut:
        return TrashListingOut(
            folders=[self._folder_out(f) for f in self.repo.trashed_folders(tenant_id)],
            files=[self._file_out(f) for f in self.repo.trashed_files(tenant_id)],
        )

    def restore(self, tenant_id: str, folder_ids: List[str], file_ids: List[str]) -> None:
        for fid in folder_ids:
            sub_ids = list(self.repo.subtree_folder_ids(tenant_id, fid))
            for sub_id in sub_ids:
                sub = self.repo.get_folder(tenant_id, sub_id)
                if sub:
                    sub.is_deleted = False
                    sub.deleted_at = None
                    sub.deleted_by = None
            for file in self.repo.files_in_folders(tenant_id, sub_ids):
                file.is_deleted = False
                file.deleted_at = None
                file.deleted_by = None
            # The TOP restored folder may now clash with a live sibling - D9
            # requires a re-collision-check on un-delete (the restored top is
            # still flagged at name-compute time, so it excludes itself).
            top = self.repo.get_folder(tenant_id, fid)
            if top:
                top.name = self._unique_folder_name(
                    tenant_id, top.parent_id, top.name, exclude_id=top.id
                )
        for fid in file_ids:
            file = self.repo.get_file(tenant_id, fid)
            if file:
                # Re-collision-check against LIVE siblings BEFORE un-deleting -
                # file_by_name excludes is_deleted rows, so the restored file
                # (still flagged here) doesn't match itself.
                file.name = self._unique_name(tenant_id, file.folder_id, file.name)
                file.is_deleted = False
                file.deleted_at = None
                file.deleted_by = None
        self.db.commit()

    def purge(self, tenant_id: str, folder_ids: List[str], file_ids: List[str]) -> None:
        storage = storage_for_tenant(self.db, tenant_id)
        drop_folder_ids: set = set()
        for fid in folder_ids:
            drop_folder_ids |= self.repo.subtree_folder_ids(tenant_id, fid)
        target_files: List[File] = []
        if drop_folder_ids:
            target_files.extend(
                self.repo.files_in_folders(tenant_id, list(drop_folder_ids))
            )
        for fid in file_ids:
            file = self.repo.get_file(tenant_id, fid)
            if file:
                target_files.append(file)

        file_ids_all = [f.id for f in target_files]
        for v in self.repo.all_versions_for_files(file_ids_all):
            try:
                storage.delete(v.storage_key)
            except Exception:  # noqa: BLE001 - a storage hiccup must not 500 a purge
                pass
            self.db.delete(v)
        for f in target_files:
            self.db.delete(f)
        for sub_id in drop_folder_ids:
            sub = self.repo.get_folder(tenant_id, sub_id)
            if sub:
                self.db.delete(sub)
        self.db.commit()

    def versions(self, tenant_id: str, file_id: str) -> List[FileVersionOut]:
        file = self.repo.get_file(tenant_id, file_id)
        if file is None:
            raise DocumentNotFound()
        return [self._version_out(v) for v in self.repo.versions(file_id)]

    # ---- upload ----

    def _unique_name(self, tenant_id: str, folder_id: Optional[str], name: str) -> str:
        if self.repo.file_by_name(tenant_id, folder_id, name) is None:
            return name
        stem, dot, ext = name.rpartition(".")
        base, suffix = (stem, f".{ext}") if dot else (name, "")
        for n in range(1, 1000):
            candidate = f"{base} ({n}){suffix}"
            if self.repo.file_by_name(tenant_id, folder_id, candidate) is None:
                return candidate
        return f"{base} ({datetime.now(timezone.utc).timestamp()}){suffix}"

    def _unique_folder_name(
        self, tenant_id: str, parent_id: Optional[str], name: str, exclude_id: Optional[str] = None
    ) -> str:
        if not self.repo.folder_name_taken(tenant_id, parent_id, name, exclude_id):
            return name
        for n in range(1, 1000):
            candidate = f"{name} ({n})"
            if not self.repo.folder_name_taken(tenant_id, parent_id, candidate, exclude_id):
                return candidate
        return f"{name} ({datetime.now(timezone.utc).timestamp()})"

    def upload(
        self,
        tenant_id: str,
        folder_id: Optional[str],
        filename: str,
        content: bytes,
        attachment_type_id: Optional[str],
        conflict: Optional[str],
        actor: Optional[User],
        *,
        actor_id: Optional[str] = None,
    ) -> FileOut:
        """Upload pipeline. ``actor`` is the authenticated User, or None for an
        anonymous public-edit write - in which case ``actor_id`` carries the
        synthetic ``share:{token}`` id so the audit/file event is attributed to
        the share, never a User (D6). ``created_by``/``uploaded_by`` stay NULL
        for anonymous writes."""
        author_id = actor.id if actor else None
        # 1. Sniff hard-floor - non-overridable.
        sniffed = detect_document_mime(content)
        if sniffed is None:
            raise UploadRejected("This file type isn't allowed for security reasons.")

        # 2. Size policy (per-type cap else tenant default).
        settings = self._settings_row(tenant_id)
        ext = _ext(filename)
        a_type: Optional[AttachmentType] = None
        if attachment_type_id:
            a_type = self.repo.get_type(tenant_id, attachment_type_id)
            if a_type is None:
                raise DocumentNotFound()
        cap_mb = (a_type.max_mb if a_type and a_type.max_mb else None) or settings.default_max_file_mb
        if len(content) > cap_mb * MB:
            raise UploadRejected(f'"{filename}" is larger than the {cap_mb} MB limit.')
        if a_type and a_type.allowed_exts_json and ext not in a_type.allowed_exts_json:
            raise UploadRejected(f"{a_type.name} doesn't accept .{ext} files.")

        # 3. Quota (versions are retained, so usage only grows).
        if settings.storage_quota_mb is not None:
            if self.repo.used_bytes(tenant_id) + len(content) > settings.storage_quota_mb * MB:
                raise QuotaExceeded()

        # 4. Collision.
        existing = self.repo.file_by_name(tenant_id, folder_id, filename)
        if existing is not None and not conflict:
            raise UploadConflict(filename, existing.id)

        storage = storage_for_tenant(self.db, tenant_id)

        if existing is not None and conflict == "replace":
            file = existing
            action = "updated"
        else:
            name = (
                self._unique_name(tenant_id, folder_id, filename)
                if existing is not None and conflict == "keep_both"
                else filename
            )
            file = File(
                tenant_id=tenant_id,
                folder_id=folder_id,
                name=name,
                attachment_type_id=attachment_type_id,
                created_by=author_id,
            )
            self.repo.add_file(file)
            action = "created"

        ordinal = len(self.repo.versions(file.id)) + 1
        version = FileVersion(
            file_id=file.id,
            ordinal=ordinal,
            storage_key="",  # set after store (needs the version id for the key)
            size_bytes=len(content),
            mime=sniffed,
            uploaded_by=author_id,
        )
        self.repo.add_version(version)
        # Quarantine order: rows exist → store bytes → set the real key.
        version.storage_key = storage.save(
            f"documents/{file.id}/{version.id}", content, sniffed
        )
        file.current_version_id = version.id
        if action == "updated" and attachment_type_id is not None:
            file.attachment_type_id = attachment_type_id
        self.db.flush()

        emit_entity_event(
            self.db, "file", action, file, tenant_id=tenant_id,
            actor=actor, actor_id=actor_id,
        )
        self.db.commit()
        return self._file_out(file)

    # ---- serve ----

    def file_content(
        self, tenant_id: str, file_id: str
    ) -> Optional[Tuple[str, str, str]]:
        """(storage_key, mime, filename) for the current version, or None."""
        file = self.repo.get_file(tenant_id, file_id)
        if file is None or file.is_deleted:
            return None
        current = self.repo.current_version(file)
        if current is None:
            return None
        return current.storage_key, current.mime, file.name

    # ---- download jobs (ZIP) ----

    def request_zip(
        self,
        tenant_id: str,
        user_id: str,
        file_ids: Optional[List[str]],
        folder_ids: Optional[List[str]],
    ) -> DownloadJobOut:
        files = self._collect_zip_files(tenant_id, file_ids, folder_ids)
        filename = "documents.zip"
        # A single folder + no loose files → name the zip after that folder.
        if folder_ids and len(folder_ids) == 1 and not file_ids:
            folder = self.repo.get_folder(tenant_id, folder_ids[0])
            if folder:
                filename = f"{folder.name}.zip"
        job = DownloadJob(
            tenant_id=tenant_id,
            user_id=user_id,
            filename=filename,
            file_count=len(files),
            status=DOWNLOAD_PENDING,
        )
        self.repo.add_job(job)
        self.db.commit()
        # Dev/test run inline (eager); prod offloads to Celery (same builder).
        self._build_zip(tenant_id, job.id, [f.id for f in files])
        self.db.refresh(job)
        return self._job_out(job)

    def _collect_zip_files(
        self,
        tenant_id: str,
        file_ids: Optional[List[str]],
        folder_ids: Optional[List[str]],
    ) -> List[File]:
        seen: set = set()
        out: List[File] = []
        for fid in file_ids or []:
            f = self.repo.get_file(tenant_id, fid)
            if f and not f.is_deleted and f.id not in seen:
                seen.add(f.id)
                out.append(f)
        if folder_ids:
            subtree: set = set()
            for folder_id in folder_ids:
                subtree |= self.repo.subtree_folder_ids(tenant_id, folder_id)
            for f in self.repo.files_in_folders(tenant_id, list(subtree)):
                if not f.is_deleted and f.id not in seen:
                    seen.add(f.id)
                    out.append(f)
        return out

    def _build_zip(self, tenant_id: str, job_id: str, file_ids: List[str]) -> None:
        job = (
            self.db.query(DownloadJob)
            .filter(DownloadJob.id == job_id, DownloadJob.tenant_id == tenant_id)
            .first()
        )
        if job is None:
            return
        storage = storage_for_tenant(self.db, tenant_id)
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                used_names: set = set()
                for fid in file_ids:
                    file = self.repo.get_file(tenant_id, fid)
                    if file is None or file.is_deleted:
                        continue
                    current = self.repo.current_version(file)
                    if current is None:
                        continue
                    data = self._read_blob(storage, current.storage_key)
                    if data is None:
                        continue
                    arcname = file.name
                    n = 1
                    while arcname in used_names:
                        stem, dot, ext = file.name.rpartition(".")
                        arcname = f"{stem} ({n}).{ext}" if dot else f"{file.name} ({n})"
                        n += 1
                    used_names.add(arcname)
                    zf.writestr(arcname, data)
            key = storage.save(f"downloads/{job.id}.zip", buffer.getvalue(), "application/zip")
            job.zip_storage_key = key
            job.status = DOWNLOAD_READY
            job.ready_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001 - a failed build marks the job, never 500s
            job.status = DOWNLOAD_FAILED
            job.error = str(exc)[:500]
        self.db.commit()

    @staticmethod
    def _read_blob(storage, key: str) -> Optional[bytes]:
        try:
            location, value = storage.resolve(key)
        except Exception:  # noqa: BLE001
            return None
        try:
            if location == "path":
                with open(value, "rb") as fh:
                    return fh.read()
            with urllib.request.urlopen(value, timeout=30) as resp:  # noqa: S310
                return resp.read()
        except Exception:  # noqa: BLE001
            return None

    def list_jobs(self, tenant_id: str, user_id: str) -> List[DownloadJobOut]:
        return [self._job_out(j) for j in self.repo.list_jobs(tenant_id, user_id)]

    def job_zip(
        self, tenant_id: str, user_id: str, job_id: str
    ) -> Tuple[str, str]:
        """(storage_key, filename) for a READY job - for the authed serve route."""
        job = self.repo.get_job(tenant_id, user_id, job_id)
        if job is None or job.zip_storage_key is None or job.status != DOWNLOAD_READY:
            raise JobNotReady()
        return job.zip_storage_key, job.filename

    def _job_out(self, job: DownloadJob) -> DownloadJobOut:
        return DownloadJobOut(
            id=job.id,
            filename=job.filename,
            status=job.status,
            file_count=job.file_count,
            error=job.error,
            created_at=job.created_at,
            ready_at=job.ready_at,
        )

    # ---- attachment types ----

    def _type_out(self, t: AttachmentType) -> AttachmentTypeOut:
        return AttachmentTypeOut(
            id=t.id,
            name=t.name,
            description=t.description,
            allowed_exts=list(t.allowed_exts_json or []),
            max_mb=t.max_mb,
            file_count=self.repo.type_file_count(t.tenant_id, t.id),
            created_at=t.created_at,
            updated_at=t.updated_at,
        )

    def list_types(
        self,
        tenant_id: str,
        *,
        page: int,
        page_size: int,
        search: Optional[str],
        sort_by: Optional[str],
        sort_dir: str,
    ) -> Tuple[List[AttachmentTypeOut], int]:
        rows, total = self.repo.paginate_types(
            tenant_id, page=page, page_size=page_size, search=search,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return [self._type_out(t) for t in rows], total

    def get_type(self, tenant_id: str, type_id: str) -> AttachmentTypeOut:
        t = self.repo.get_type(tenant_id, type_id)
        if t is None:
            raise DocumentNotFound()
        return self._type_out(t)

    def create_type(
        self,
        tenant_id: str,
        name: str,
        description: Optional[str],
        allowed_exts: List[str],
        max_mb: Optional[int],
    ) -> AttachmentTypeOut:
        row = AttachmentType(
            tenant_id=tenant_id,
            name=name.strip(),
            description=(description or None),
            allowed_exts_json=[e.strip().lstrip(".").lower() for e in allowed_exts if e.strip()],
            max_mb=max_mb,
        )
        self.repo.add_type(row)
        self.db.commit()
        return self._type_out(row)

    def update_type(self, tenant_id: str, type_id: str, **patch) -> AttachmentTypeOut:
        t = self.repo.get_type(tenant_id, type_id)
        if t is None:
            raise DocumentNotFound()
        if patch.get("name") is not None:
            t.name = patch["name"].strip()
        if "description" in patch:
            t.description = patch["description"] or None
        if patch.get("allowed_exts") is not None:
            t.allowed_exts_json = [
                e.strip().lstrip(".").lower() for e in patch["allowed_exts"] if e.strip()
            ]
        if "max_mb" in patch:
            t.max_mb = patch["max_mb"]
        self.db.commit()
        return self._type_out(t)

    def delete_type(self, tenant_id: str, type_id: str) -> None:
        t = self.repo.get_type(tenant_id, type_id)
        if t is None:
            raise DocumentNotFound()
        # Files keep their bytes; they just lose the category.
        for f in (
            self.db.query(File)
            .filter(File.tenant_id == tenant_id, File.attachment_type_id == type_id)
            .all()
        ):
            f.attachment_type_id = None
        self.db.delete(t)
        self.db.commit()

    # ---- settings ----

    def _settings_row(self, tenant_id: str) -> DocumentSettings:
        row = self.repo.get_settings(tenant_id)
        if row is None:
            row = DocumentSettings(tenant_id=tenant_id)
            self.repo.add_settings(row)
            self.db.commit()
        return row

    def get_settings(self, tenant_id: str) -> DocumentSettingsOut:
        row = self._settings_row(tenant_id)
        return DocumentSettingsOut(
            public_sharing=row.public_sharing,
            default_max_file_mb=row.default_max_file_mb,
            storage_quota_mb=row.storage_quota_mb,
            used_bytes=self.repo.used_bytes(tenant_id),
        )

    def update_settings(self, tenant_id: str, **patch) -> DocumentSettingsOut:
        row = self._settings_row(tenant_id)
        if patch.get("public_sharing") is not None:
            if patch["public_sharing"] not in SHARING_VALUES:
                raise UploadRejected("Invalid sharing policy.")
            row.public_sharing = patch["public_sharing"]
        if patch.get("default_max_file_mb") is not None:
            row.default_max_file_mb = max(1, int(patch["default_max_file_mb"]))
        if "storage_quota_mb" in patch:
            row.storage_quota_mb = patch["storage_quota_mb"]
        self.db.commit()
        return self.get_settings(tenant_id)

"""Document management (the Drive) endpoints (plan sprint-3/04) — HTTP only
(Router → Service → Repository). One ``router`` (``/documents``) covering Drive
navigation, folder/file ops, multipart upload, the CSP-sandbox content serve
route, trash, attachment types, settings and the async ZIP download jobs.

Gating (D15): browse/preview/download = ``documents.read``; mutations =
``documents.manage``; types + settings = ``documents.configure``. (Sharing's
``documents.share`` lands in slice 05.) Error contracts the frontend pins:
upload 409 → ``{"fileName","existingFileId"}``; 413 quota; 415 type/size reject
(plain string); 422 cycle.
"""
import re
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import (
    effective_permission_keys,
    get_current_user,
    get_db,
    require_permission,
)
from app.models.user import User
from app.services.throttle import (
    ThrottleService,
    Throttled,
    client_ip,
)
from app.schemas.document import (
    AttachmentTypeCreateRequest,
    AttachmentTypeListResponse,
    AttachmentTypeOut,
    AttachmentTypeUpdateRequest,
    CreateFolderRequest,
    DocumentSettingsOut,
    DocumentSettingsUpdateRequest,
    DownloadJobOut,
    FileLinkCreateRequest,
    FileLinkOut,
    FileOut,
    FileVersionOut,
    FolderListingOut,
    FolderOut,
    IdsRequest,
    MoveRequest,
    PublicShareView,
    PublicUnlockRequest,
    RenameRequest,
    ShareEnsureRequest,
    ShareListResponse,
    ShareOut,
    SharedWithMeItem,
    ShareUpdateRequest,
    ShareUserOut,
    TrashListingOut,
    ZipRequest,
)
from app.services.document_service import (
    CycleError,
    DocumentNotFound,
    DocumentService,
    JobNotReady,
    QuotaExceeded,
    UploadConflict,
    UploadRejected,
)
from app.services.share_service import (
    ShareCapExceeded,
    ShareForbidden,
    ShareInvalid,
    ShareNotFound,
    SharePasswordInvalid,
    ShareService,
    SHARE_HONEYPOT_FIELD,
)

router = APIRouter()
public_router = APIRouter()

# Hard read cap (a generous ceiling so an oversize body is never buffered whole;
# the per-type / tenant-default policy cap is enforced in the service).
READ_CAP_BYTES = 200 * 1024 * 1024


def _none_if_blank(value: Optional[str]) -> Optional[str]:
    return value or None


def _content_disposition(dispo: str, filename: str) -> str:
    """Safe Content-Disposition — the file name is tenant-controlled (rename only
    strips whitespace), so a quote/backslash/CRLF would inject the header. Emit a
    sanitized ASCII fallback + an RFC 5987 ``filename*`` for the real (UTF-8) name."""
    from urllib.parse import quote

    ascii_name = re.sub(r'[\r\n"\\]', "", filename.encode("ascii", "ignore").decode("ascii")).strip()
    ascii_name = ascii_name or "download"
    encoded = quote(filename, safe="")
    return f"{dispo}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _serve_blob(
    db: Session,
    tenant_id: str,
    storage_key: str,
    mime: str,
    filename: str,
    disposition: str,
):
    """Serve a stored blob CSP-sandboxed + nosniff (a blob may be script-bearing
    markup — sandbox keeps it inert). Presigned URLs expire → never
    immutable-cache. Shared by the Drive serve route + the public share route."""
    from app.services.storage import storage_for_tenant

    try:
        location, value = storage_for_tenant(db, tenant_id).resolve(storage_key)
    except Exception:  # noqa: BLE001 — unresolvable key (connection gone)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    dispo = "attachment" if disposition == "attachment" else "inline"
    headers = {
        "Content-Disposition": _content_disposition(dispo, filename),
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    }
    if location in ("presigned", "url"):
        return RedirectResponse(value, headers=headers)
    return FileResponse(value, media_type=mime, headers=headers)


# ---- navigation ----


@router.get("/folders", response_model=FolderListingOut)
def list_folder(
    folder_id: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> FolderListingOut:
    try:
        return DocumentService(db).list_folder(current_user.tenant_id, _none_if_blank(folder_id))
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")


# ---- folder ops ----


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
def create_folder(
    body: CreateFolderRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> FolderOut:
    try:
        return DocumentService(db).create_folder(
            current_user.tenant_id, body.parentId, body.name, current_user
        )
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent folder not found.")


@router.patch("/folders/{folder_id}", response_model=FolderOut)
def rename_folder(
    folder_id: str,
    body: RenameRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> FolderOut:
    try:
        return DocumentService(db).rename_folder(current_user.tenant_id, folder_id, body.name)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")


@router.post("/folders/move", status_code=status.HTTP_204_NO_CONTENT)
def move_folders(
    body: MoveRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    _move(db, current_user, body.ids, [], body.targetFolderId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/folders/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_folders(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).delete(current_user.tenant_id, body.ids, [], current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/folders/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_folders(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).restore(current_user.tenant_id, body.ids, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/folders/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_folders(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).purge(current_user.tenant_id, body.ids, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- file ops ----


@router.patch("/files/{file_id}", response_model=FileOut)
def rename_file(
    file_id: str,
    body: RenameRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> FileOut:
    try:
        return DocumentService(db).rename_file(
            current_user.tenant_id, file_id, body.name, current_user
        )
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")


@router.post("/files/move", status_code=status.HTTP_204_NO_CONTENT)
def move_files(
    body: MoveRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    _move(db, current_user, [], body.ids, body.targetFolderId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/files/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_files(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).delete(current_user.tenant_id, [], body.ids, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/files/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_files(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).restore(current_user.tenant_id, [], body.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/files/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_files(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    DocumentService(db).purge(current_user.tenant_id, [], body.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{file_id}/versions", response_model=List[FileVersionOut])
def file_versions(
    file_id: str,
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> List[FileVersionOut]:
    try:
        return DocumentService(db).versions(current_user.tenant_id, file_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")


def _move(
    db: Session,
    user: User,
    folder_ids: List[str],
    file_ids: List[str],
    target: Optional[str],
) -> None:
    try:
        DocumentService(db).move(
            user.tenant_id, folder_ids, file_ids, _none_if_blank(target), user
        )
    except CycleError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Can't move a folder into itself."
        )
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Destination not found.")


# ---- upload ----


@router.post("/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    attachment_type_id: Optional[str] = Form(None),
    on_conflict: Optional[str] = Form(None),
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> FileOut:
    content = await file.read(READ_CAP_BYTES + 1)
    if len(content) > READ_CAP_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large."
        )
    try:
        return DocumentService(db).upload(
            current_user.tenant_id,
            _none_if_blank(folder_id),
            file.filename or "file",
            content,
            _none_if_blank(attachment_type_id),
            _none_if_blank(on_conflict),
            current_user,
        )
    except UploadConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"fileName": exc.file_name, "existingFileId": exc.existing_file_id},
        )
    except QuotaExceeded:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Storage quota exceeded."
        )
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, exc.message)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder or type not found.")


# ---- content serve (CSP-sandboxed) ----


@router.get("/files/{file_id}/content")
def file_content(
    file_id: str,
    disposition: str = Query("inline"),
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
):
    """Serve a file's current version (D10/D11). Authed + tenant-scoped;
    CSP-sandboxed + nosniff (a stored blob may be script-bearing markup —
    sandbox keeps it inert). Presigned URLs expire → never immutable-cache."""
    from app.services.storage import storage_for_tenant

    found = DocumentService(db).file_content(current_user.tenant_id, file_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    storage_key, mime, filename = found
    try:
        location, value = storage_for_tenant(db, current_user.tenant_id).resolve(storage_key)
    except Exception:  # noqa: BLE001 — unresolvable key (connection gone)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    dispo = "attachment" if disposition == "attachment" else "inline"
    headers = {
        "Content-Disposition": _content_disposition(dispo, filename),
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    }
    if location in ("presigned", "url"):
        return RedirectResponse(value, headers=headers)
    return FileResponse(value, media_type=mime, headers=headers)


# ---- trash ----


@router.get("/trash", response_model=TrashListingOut)
def list_trash(
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> TrashListingOut:
    return DocumentService(db).list_trash(current_user.tenant_id)


# ---- download jobs ----


@router.post("/download-jobs", response_model=DownloadJobOut, status_code=status.HTTP_201_CREATED)
def create_download_job(
    body: ZipRequest,
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> DownloadJobOut:
    return DocumentService(db).request_zip(
        current_user.tenant_id, current_user.id, body.fileIds, body.folderIds
    )


@router.get("/download-jobs", response_model=List[DownloadJobOut])
def list_download_jobs(
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> List[DownloadJobOut]:
    return DocumentService(db).list_jobs(current_user.tenant_id, current_user.id)


@router.get("/download-jobs/{job_id}/content")
def download_job_content(
    job_id: str,
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
):
    """Stream a READY ZIP job's bytes (authed, own jobs only)."""
    from app.services.storage import storage_for_tenant

    try:
        storage_key, filename = DocumentService(db).job_zip(
            current_user.tenant_id, current_user.id, job_id
        )
    except JobNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, "Download is not ready.")
    try:
        location, value = storage_for_tenant(db, current_user.tenant_id).resolve(storage_key)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Download not found.")
    headers = {
        "Content-Disposition": _content_disposition("attachment", filename),
        "Cache-Control": "private, max-age=60",
    }
    if location in ("presigned", "url"):
        return RedirectResponse(value, headers=headers)
    return FileResponse(value, media_type="application/zip", headers=headers)


# ---- attachment types ----


@router.get("/types", response_model=AttachmentTypeListResponse)
def list_types(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> AttachmentTypeListResponse:
    rows, total = DocumentService(db).list_types(
        current_user.tenant_id,
        page=page, page_size=page_size, search=search,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    return AttachmentTypeListResponse(data=rows, total=total, page=page)


@router.get("/types/export", response_class=PlainTextResponse)
def export_types(
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> str:
    rows, _ = DocumentService(db).list_types(
        current_user.tenant_id, page=0, page_size=10000, search=None,
        sort_by="name", sort_dir="asc",
    )
    lines = ["Name,Description,Allowed types,Max MB,Files"]
    for t in rows:
        cells = [
            t.name, t.description or "", " ".join(t.allowed_exts),
            str(t.max_mb or ""), str(t.file_count),
        ]
        lines.append(",".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cells))
    return "\n".join(lines)


@router.get("/types/{type_id}", response_model=AttachmentTypeOut)
def get_type(
    type_id: str,
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> AttachmentTypeOut:
    try:
        return DocumentService(db).get_type(current_user.tenant_id, type_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found.")


@router.post("/types", response_model=AttachmentTypeOut, status_code=status.HTTP_201_CREATED)
def create_type(
    body: AttachmentTypeCreateRequest,
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> AttachmentTypeOut:
    return DocumentService(db).create_type(
        current_user.tenant_id, body.name, body.description, body.allowedExts, body.maxMb
    )


@router.patch("/types/{type_id}", response_model=AttachmentTypeOut)
def update_type(
    type_id: str,
    body: AttachmentTypeUpdateRequest,
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> AttachmentTypeOut:
    fields = body.model_fields_set
    patch = {}
    if "name" in fields and body.name is not None:
        patch["name"] = body.name
    if "description" in fields:
        patch["description"] = body.description
    if "allowedExts" in fields and body.allowedExts is not None:
        patch["allowed_exts"] = body.allowedExts
    if "maxMb" in fields:
        patch["max_mb"] = body.maxMb
    try:
        return DocumentService(db).update_type(current_user.tenant_id, type_id, **patch)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found.")


@router.delete("/types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_type(
    type_id: str,
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        DocumentService(db).delete_type(current_user.tenant_id, type_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- settings ----


@router.get("/settings", response_model=DocumentSettingsOut)
def get_settings(
    # Readable by any Drive user — the usage bar + caps need it; only writing
    # the policy requires documents.configure (below).
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> DocumentSettingsOut:
    return DocumentService(db).get_settings(current_user.tenant_id)


@router.put("/settings", response_model=DocumentSettingsOut)
def update_settings(
    body: DocumentSettingsUpdateRequest,
    current_user: User = Depends(require_permission("documents.configure")),
    db: Session = Depends(get_db),
) -> DocumentSettingsOut:
    fields = body.model_fields_set
    patch = {}
    if body.publicSharing is not None:
        patch["public_sharing"] = body.publicSharing
    if body.defaultMaxFileMb is not None:
        patch["default_max_file_mb"] = body.defaultMaxFileMb
    # storageQuotaMb: present-but-null = unlimited; absent = leave unchanged.
    if "storageQuotaMb" in fields:
        patch["storage_quota_mb"] = body.storageQuotaMb
    try:
        return DocumentService(db).update_settings(current_user.tenant_id, **patch)
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)


# ---- sharing (slice-05, Google-Drive model) ----
#
# A target has ONE stable share (token never changes). `ensure` get-or-creates
# it (opening the dialog); `PATCH` edits general-access / capability / people /
# expiry / password / caps in place. Both gated `documents.share`; setting
# general-access = public+edit also needs `documents.manage` (can't hand out
# write you lack). The `by-token` resolve/serve are gated `get_current_user`
# ONLY (a workspace/restricted link is opened by any authorized tenant member).


def _share_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ShareNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    if isinstance(exc, ShareForbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, exc.message)
    if isinstance(exc, ShareInvalid):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)
    if isinstance(exc, ShareCapExceeded):
        return HTTPException(status.HTTP_409_CONFLICT, exc.message)
    return HTTPException(status.HTTP_400_BAD_REQUEST, "Bad request.")


@router.post("/shares/ensure", response_model=ShareOut)
def ensure_share(
    body: ShareEnsureRequest,
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> ShareOut:
    try:
        return ShareService(db).ensure(
            current_user.tenant_id, current_user, body.targetKind, body.targetId
        )
    except (ShareNotFound, ShareInvalid) as exc:
        raise _share_http(exc)


@router.patch("/shares/{share_id}", response_model=ShareOut)
def update_share(
    share_id: str,
    body: ShareUpdateRequest,
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> ShareOut:
    can_manage = "documents.manage" in effective_permission_keys(current_user)
    try:
        return ShareService(db).update(current_user.tenant_id, share_id, can_manage, body)
    except (ShareNotFound, ShareForbidden, ShareInvalid) as exc:
        raise _share_http(exc)


@router.get("/shares", response_model=ShareListResponse)
def list_shares(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    segment: str = Query("active"),
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> ShareListResponse:
    rows, total = ShareService(db).list_shares(
        current_user.tenant_id,
        page=page, page_size=page_size, search=search,
        sort_by=sort_by, sort_dir=sort_dir, disabled=(segment == "revoked"),
    )
    return ShareListResponse(data=rows, total=total, page=page)


@router.get("/shares/export", response_class=PlainTextResponse)
def export_shares(
    segment: str = Query("active"),
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> str:
    rows, _ = ShareService(db).list_shares(
        current_user.tenant_id, page=0, page_size=10000, search=None,
        sort_by="createdAt", sort_dir="desc", disabled=(segment == "revoked"),
    )
    lines = ["Target,Kind,Access,Capability,Creator,Expiry,Created"]
    for s in rows:
        cells = [
            s.target_name or "", s.target_kind, s.general_access, s.capability,
            s.created_by_name or "", s.expires_at.isoformat() if s.expires_at else "",
            s.created_at.isoformat(),
        ]
        lines.append(",".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cells))
    return "\n".join(lines)


@router.post("/shares/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_shares(
    body: IdsRequest,
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> Response:
    ShareService(db).revoke(current_user.tenant_id, body.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shared-with-me", response_model=List[SharedWithMeItem])
def shared_with_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Roots shared TO the signed-in member (the "Shared with me" drive). Any
    authenticated tenant member — not gated on documents.read (a recipient may
    not have Drive access of their own)."""
    return ShareService(db).list_shared_with_me(current_user.tenant_id, current_user)


@router.get("/shares/users", response_model=List[ShareUserOut])
def list_share_users(
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
):
    return ShareService(db).list_tenant_users(current_user.tenant_id, _none_if_blank(search))


@router.get("/shares/target", response_model=Optional[ShareOut])
def get_target_share(
    kind: str = Query(...),
    id: str = Query(...),
    current_user: User = Depends(require_permission("documents.share")),
    db: Session = Depends(get_db),
) -> Optional[ShareOut]:
    """The ONE active share for a target, or null (the dialog calls /ensure to
    create it on demand)."""
    return ShareService(db).list_target(current_user.tenant_id, kind, id)


@router.get("/shares/by-token/{token}", response_model=PublicShareView)
def resolve_share_authed(
    token: str,
    folder_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublicShareView:
    """Resolve an internal/user/public link as the authenticated caller (any
    tenant member — not necessarily a Sharer). Wrong tenant / not-on-allow-list
    = 403; unknown/disabled = 404."""
    try:
        return ShareService(db).resolve(
            token, user=current_user, public_route=False,
            folder_id=_none_if_blank(folder_id), password_ok=True,
        )
    except (ShareNotFound, ShareForbidden) as exc:
        raise _share_http(exc)


@router.get("/shares/by-token/{token}/file/{file_id}")
def serve_share_file_authed(
    token: str,
    file_id: str,
    disposition: str = Query("inline"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = ShareService(db)
    try:
        storage_key, mime, filename = service.serve_file(
            token, file_id, user=current_user, public_route=False, password=None,
        )
    except (ShareNotFound, ShareForbidden, SharePasswordInvalid) as exc:
        raise _share_http(exc) if not isinstance(exc, SharePasswordInvalid) else \
            HTTPException(status.HTTP_403_FORBIDDEN, "Password required.")
    tenant_id = service.tenant_for_token(token)
    return _serve_blob(db, tenant_id, storage_key, mime, filename, disposition)


@router.post("/shares/by-token/{token}/upload", status_code=status.HTTP_204_NO_CONTENT)
async def upload_share_file_authed(
    token: str,
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """An authorized editor uploads into a shared folder from the in-app scoped
    view (attributed to THEM, no honeypot/throttle — they're authenticated)."""
    content = await file.read(READ_CAP_BYTES + 1)
    if len(content) > READ_CAP_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large.")
    try:
        ShareService(db).public_upload(
            token, file.filename or "file", content,
            user=current_user, password=None, folder_id=_none_if_blank(folder_id),
        )
    except (ShareNotFound, ShareForbidden, ShareCapExceeded) as exc:
        raise _share_http(exc)
    except QuotaExceeded:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Storage quota exceeded.")
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, exc.message)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- file_links polymorphic seam (D8 — isolation-tested only) ----


@router.post("/file-links", response_model=FileLinkOut, status_code=status.HTTP_201_CREATED)
def create_file_link(
    body: FileLinkCreateRequest,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> FileLinkOut:
    try:
        return ShareService(db).link_file(
            current_user.tenant_id, body.entityType, body.entityId, body.fileId, current_user
        )
    except ShareInvalid as exc:
        raise _share_http(exc)


@router.get("/file-links", response_model=List[FileLinkOut])
def list_file_links(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    current_user: User = Depends(require_permission("documents.read")),
    db: Session = Depends(get_db),
) -> List[FileLinkOut]:
    return ShareService(db).list_links(current_user.tenant_id, entity_type, entity_id)


@router.delete("/file-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_link(
    link_id: str,
    current_user: User = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        ShareService(db).unlink_file(current_user.tenant_id, link_id)
    except ShareInvalid as exc:
        raise _share_http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- public (pre-auth) share surface (D9) ----
#
# The token is a globally-unique bearer capability that self-identifies the
# tenant — no slug in path/subdomain. Unknown/disabled/over-ceiling = uniform
# 404 (no enumeration); expired = a friendly 200 closed state. Password gate +
# anonymous upload ride the OWN `doc_share` throttle bucket.


@public_router.get("/{token}", response_model=PublicShareView)
def public_resolve_share(
    token: str,
    folder_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> PublicShareView:
    try:
        return ShareService(db).resolve(
            token, user=None, public_route=True, folder_id=_none_if_blank(folder_id),
        )
    except ShareNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


@public_router.post("/{token}/unlock", response_model=PublicShareView)
def public_unlock_share(
    token: str,
    body: PublicUnlockRequest,
    request: Request,
    folder_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> PublicShareView:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    try:
        throttle.enforce_doc_share(ip=ip)
    except Throttled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    service = ShareService(db)
    if not service.verify_unlock(token, body.password):
        throttle.record_doc_share(ip=ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect password.")
    try:
        return service.resolve(
            token, user=None, public_route=True,
            folder_id=_none_if_blank(folder_id), password_ok=True,
        )
    except ShareNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


@public_router.get("/{token}/file/{file_id}")
def public_serve_share_file(
    token: str,
    file_id: str,
    request: Request,
    disposition: str = Query("inline"),
    db: Session = Depends(get_db),
):
    password = request.headers.get("x-share-password")
    service = ShareService(db)
    try:
        storage_key, mime, filename = service.serve_file(
            token, file_id, user=None, public_route=True, password=password,
        )
    except ShareNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    except SharePasswordInvalid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password required.")
    tenant_id = service.tenant_for_token(token)
    return _serve_blob(db, tenant_id, storage_key, mime, filename, disposition)


@public_router.post("/{token}/upload", status_code=status.HTTP_204_NO_CONTENT)
async def public_share_upload(
    token: str,
    request: Request,
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> Response:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    try:
        throttle.enforce_doc_share(ip=ip)
    except Throttled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many uploads. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    throttle.record_doc_share(ip=ip)

    # Honeypot — a non-empty value = a bot. Return 204, store NOTHING (never tip
    # off the bot — D6). The field rides the multipart form.
    form = await request.form()
    honeypot = (form.get(SHARE_HONEYPOT_FIELD) or "")
    if isinstance(honeypot, str) and honeypot.strip():
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    content = await file.read(READ_CAP_BYTES + 1)
    if len(content) > READ_CAP_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large.")
    password = request.headers.get("x-share-password")
    service = ShareService(db)
    try:
        service.public_upload(
            token, file.filename or "file", content,
            password=password, folder_id=_none_if_blank(folder_id),
        )
    except ShareNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    except SharePasswordInvalid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password required.")
    except ShareCapExceeded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message)
    except QuotaExceeded:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Storage quota exceeded.")
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, exc.message)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

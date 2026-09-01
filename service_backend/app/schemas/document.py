"""Document management (the Drive) wire schemas (plan sprint-3/04) - camelCase
out (mirror of the frontend ``types/documents.ts``). Datetime-bearing models
inherit ``ApiModel`` so every timestamp leaves the API Z-suffixed UTC (BL-012).
Request models declare camelCase field names directly (the frontend sends those
verbatim)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel


class Crumb(ApiModel):
    id: str
    name: str


# ---- files + versions ----


class FileVersionOut(ApiModel):
    id: str
    ordinal: int
    size_bytes: int = Field(serialization_alias="sizeBytes")
    mime: str
    uploaded_by: Optional[str] = Field(default=None, serialization_alias="uploadedBy")
    uploaded_by_name: Optional[str] = Field(
        default=None, serialization_alias="uploadedByName"
    )
    created_at: datetime = Field(serialization_alias="createdAt")


class FileOut(ApiModel):
    id: str
    folder_id: Optional[str] = Field(serialization_alias="folderId")
    name: str
    current_version: FileVersionOut = Field(serialization_alias="currentVersion")
    attachment_type_id: Optional[str] = Field(serialization_alias="attachmentTypeId")
    attachment_type_name: Optional[str] = Field(
        default=None, serialization_alias="attachmentTypeName"
    )
    version_count: int = Field(serialization_alias="versionCount")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    created_by_name: Optional[str] = Field(
        default=None, serialization_alias="createdByName"
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


# ---- folders ----


class FolderOut(ApiModel):
    id: str
    parent_id: Optional[str] = Field(serialization_alias="parentId")
    name: str
    path: List[Crumb] = []
    folder_count: int = Field(default=0, serialization_alias="folderCount")
    file_count: int = Field(default=0, serialization_alias="fileCount")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class FolderListingOut(ApiModel):
    folder: Optional[FolderOut] = None
    breadcrumb: List[Crumb] = []
    folders: List[FolderOut] = []
    files: List[FileOut] = []


class TrashListingOut(ApiModel):
    folders: List[FolderOut] = []
    files: List[FileOut] = []


# ---- attachment types ----


class AttachmentTypeOut(ApiModel):
    id: str
    name: str
    description: Optional[str] = None
    allowed_exts: List[str] = Field(serialization_alias="allowedExts")
    max_mb: Optional[int] = Field(serialization_alias="maxMb")
    file_count: int = Field(default=0, serialization_alias="fileCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class AttachmentTypeListResponse(ApiModel):
    data: List[AttachmentTypeOut]
    total: int
    page: int


# ---- settings ----


class DocumentSettingsOut(ApiModel):
    public_sharing: str = Field(serialization_alias="publicSharing")
    default_max_file_mb: int = Field(serialization_alias="defaultMaxFileMb")
    storage_quota_mb: Optional[int] = Field(serialization_alias="storageQuotaMb")
    used_bytes: int = Field(serialization_alias="usedBytes")


# ---- download jobs ----


class DownloadJobOut(ApiModel):
    id: str
    filename: str
    status: str
    file_count: int = Field(serialization_alias="fileCount")
    error: Optional[str] = None
    created_at: datetime = Field(serialization_alias="createdAt")
    ready_at: Optional[datetime] = Field(serialization_alias="readyAt")


class DownloadJobUrlOut(BaseModel):
    url: str
    filename: str


# ---- requests (camelCase in) ----


class CreateFolderRequest(BaseModel):
    parentId: Optional[str] = None
    name: str


class RenameRequest(BaseModel):
    name: str


class MoveRequest(BaseModel):
    ids: List[str]
    targetFolderId: Optional[str] = None


class IdsRequest(BaseModel):
    ids: List[str]


class AttachmentTypeCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    allowedExts: List[str] = []
    maxMb: Optional[int] = None


class AttachmentTypeUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allowedExts: Optional[List[str]] = None
    maxMb: Optional[int] = None


class DocumentSettingsUpdateRequest(BaseModel):
    publicSharing: Optional[str] = None
    defaultMaxFileMb: Optional[int] = None
    storageQuotaMb: Optional[int] = None


class ZipRequest(BaseModel):
    fileIds: Optional[List[str]] = None
    folderIds: Optional[List[str]] = None


# ---- sharing (slice-05, Google-Drive model) ----


class ShareUserOut(ApiModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    capability: str = "view"


class ShareOut(ApiModel):
    id: str
    target_kind: str = Field(serialization_alias="targetKind")
    target_id: str = Field(serialization_alias="targetId")
    target_name: Optional[str] = Field(default=None, serialization_alias="targetName")
    # restricted | workspace | public - the tier beyond the named people list.
    general_access: str = Field(serialization_alias="generalAccess")
    # Role for the general-access tier.
    capability: str
    token: str
    url: str
    expires_at: Optional[datetime] = Field(serialization_alias="expiresAt")
    is_expired: bool = Field(default=False, serialization_alias="isExpired")
    has_password: bool = Field(default=False, serialization_alias="hasPassword")
    max_uploads: Optional[int] = Field(default=None, serialization_alias="maxUploads")
    max_total_mb: Optional[int] = Field(default=None, serialization_alias="maxTotalMb")
    is_disabled: bool = Field(default=False, serialization_alias="isDisabled")
    # Named "People with access" (always additive), each with its own role.
    people: List[ShareUserOut] = []
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    created_by_name: Optional[str] = Field(
        default=None, serialization_alias="createdByName"
    )
    created_at: datetime = Field(serialization_alias="createdAt")


class ShareListResponse(ApiModel):
    data: List[ShareOut]
    total: int
    page: int


class SharedWithMeItem(ApiModel):
    """One root shared TO the current user (the "Shared with me" drive)."""

    token: str
    target_kind: str = Field(serialization_alias="targetKind")
    target_id: str = Field(serialization_alias="targetId")
    name: str
    capability: str
    owner_name: Optional[str] = Field(default=None, serialization_alias="ownerName")
    shared_at: datetime = Field(serialization_alias="sharedAt")


class ShareEnsureRequest(BaseModel):
    """Get-or-create the ONE stable share for a target (opening the dialog)."""

    targetKind: str
    targetId: str


class SharePersonInput(BaseModel):
    userId: str
    capability: str = "view"


class ShareUpdateRequest(BaseModel):
    """In-place edit of the stable share (Google "change who has access"). Only
    fields present are applied: ``expiresAt``/``password`` null = clear, absent =
    unchanged; ``people`` (when present) REPLACES the whole allow-list."""

    generalAccess: Optional[str] = None
    capability: Optional[str] = None
    expiresAt: Optional[datetime] = None
    password: Optional[str] = None
    maxUploads: Optional[int] = None
    maxTotalMb: Optional[int] = None
    people: Optional[List[SharePersonInput]] = None
    isDisabled: Optional[bool] = None


# ---- public share surface (pre-auth) ----


class PublicShareFileNode(ApiModel):
    id: str
    name: str
    mime: str
    size_bytes: int = Field(serialization_alias="sizeBytes")
    preview_kind: str = Field(serialization_alias="previewKind")  # image|pdf|none


class PublicShareFolderNode(ApiModel):
    id: str
    name: str


class PublicShareView(ApiModel):
    state: str  # open | password_required | closed
    message: Optional[str] = None
    tenant_name: Optional[str] = Field(default=None, serialization_alias="tenantName")
    kind: Optional[str] = None  # file | folder (when open)
    capability: Optional[str] = None  # view | edit (when open)
    title: Optional[str] = None  # file/folder name
    # File share → the single file node.
    file: Optional[PublicShareFileNode] = None
    # Folder share → the CURRENT folder listing (live-walk; folder_id descends).
    folder_id: Optional[str] = Field(default=None, serialization_alias="folderId")
    breadcrumb: List[PublicShareFolderNode] = []
    folders: List[PublicShareFolderNode] = []
    files: List[PublicShareFileNode] = []
    honeypot_field: Optional[str] = Field(
        default=None, serialization_alias="honeypotField"
    )


class PublicUnlockRequest(BaseModel):
    password: str


# ---- file_links seam (D8) ----


class FileLinkOut(ApiModel):
    id: str
    entity_type: str = Field(serialization_alias="entityType")
    entity_id: str = Field(serialization_alias="entityId")
    file_id: str = Field(serialization_alias="fileId")
    created_at: datetime = Field(serialization_alias="createdAt")


class FileLinkCreateRequest(BaseModel):
    entityType: str
    entityId: str
    fileId: str

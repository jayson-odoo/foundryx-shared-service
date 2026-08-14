/**
 * Document Management (the Drive) - wire types.
 *
 * F3 slice 1 (sprint-3/04). A Google-Drive-class repository on top of the
 * core StorageService: a navigable shared-tenant folder tree, files with
 * version history, upload/download/move/rename/trash, preview. Sharing (links,
 * tiers, public route) lands in slice 05 (sprint-3/05) - not here.
 *
 * camelCase mirrors the planned backend Pydantic schemas (`app/document_engine/
 * schemas.py`). Kept deliberately flat - a folder/file is not a block-document
 * engine; the only "document" here is the literal file blob.
 */

/** A folder node in the tenant Drive tree. */
export interface FolderRow {
  id: string;
  /** NULL = a root-level folder (direct child of the Drive root). */
  parentId: string | null;
  name: string;
  /** Convenience breadcrumb the backend resolves (root → this), excluding root. */
  path: { id: string; name: string }[];
  /** Immediate counts for the grid (folders + files, non-deleted). */
  folderCount: number;
  fileCount: number;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

/** One stored revision of a file's bytes. Replace/re-upload appends one. */
export interface FileVersionRow {
  id: string;
  /** 1-based ordinal for display ("v3"). */
  ordinal: number;
  sizeBytes: number;
  /** The magic-byte-SNIFFED mime (never the declared content-type). */
  mime: string;
  uploadedBy: string;
  uploadedByName?: string;
  createdAt: string;
}

/** A file in the Drive. Identity (id) + name are stable across versions. */
export interface FileRow {
  id: string;
  /** NULL = at the Drive root. */
  folderId: string | null;
  name: string;
  /** The current (latest) version - what previews/downloads serve. */
  currentVersion: FileVersionRow;
  /** Optional categorization (D7). */
  attachmentTypeId: string | null;
  attachmentTypeName?: string | null;
  /** Total versions kept (history depth). */
  versionCount: number;
  createdBy: string;
  createdByName?: string;
  createdAt: string;
  updatedAt: string;
}

/** Whether a file previews inline or only downloads (D10). */
export type PreviewKind = 'image' | 'pdf' | 'none';

/** A unified Drive entry for the grid (folder or file). */
export type DriveEntry =
  | ({ kind: 'folder' } & FolderRow)
  | ({ kind: 'file'; previewKind: PreviewKind } & FileRow);

/** One listing of a folder's immediate children + the folder's own crumb trail. */
export interface FolderListing {
  /** NULL when listing the Drive root. */
  folder: FolderRow | null;
  /** Breadcrumb from root → current (empty at root). */
  breadcrumb: { id: string; name: string }[];
  folders: FolderRow[];
  files: FileRow[];
}

/** Tenant-configurable file category (optional on upload). */
export interface AttachmentTypeRow {
  id: string;
  name: string;
  description: string | null;
  /** Lowercase, dot-less extensions (['pdf','docx']). Empty = any (within the floor). */
  allowedExts: string[];
  /** Per-type size cap; null = fall back to the tenant default. */
  maxMb: number | null;
  fileCount: number;
  createdAt: string;
  updatedAt: string;
}

export type PublicSharingPolicy = 'off' | 'view' | 'edit';

/** Tenant document settings (one row per tenant). */
export interface DocumentSettings {
  /** Slice-05 share ceiling; surfaced here so the form is whole, enforced in 05. */
  publicSharing: PublicSharingPolicy;
  /** Cap for uploads with no attachment type assigned. */
  defaultMaxFileMb: number;
  /** NULL = unlimited storage. */
  storageQuotaMb: number | null;
  /** Current usage (sum of non-purged version bytes), for the usage bar. */
  usedBytes: number;
}

/** Conflict resolution when a same-name file is uploaded into a folder. */
export type ConflictMode = 'replace' | 'keep_both';

/** Surfaced from a 409 the upload pipeline raises on a name collision. */
export interface UploadConflict {
  fileName: string;
  existingFileId: string;
}

/** Async ZIP (bulk/folder download) job status. */
export type DownloadJobStatus = 'pending' | 'processing' | 'ready' | 'failed';

export interface DownloadJob {
  id: string;
  filename: string;
  status: DownloadJobStatus;
  /** Number of files bundled (for the drawer label). */
  fileCount: number;
  error: string | null;
  createdAt: string;
  readyAt: string | null;
}

// ── Upload (client-session optimistic) ──────────────────────────────────────

/** Per-file lifecycle in the client-session upload drawer (no server feed). */
export type UploadFileStatus =
  | 'queued'
  | 'uploading'
  | 'done'
  | 'failed'
  /** Paused awaiting a Replace / Keep-both decision on a name collision. */
  | 'conflict';

export interface UploadFileItem {
  id: string;
  name: string;
  sizeBytes: number;
  status: UploadFileStatus;
  /** 0-100. */
  progress: number;
  error?: string;
  conflict?: UploadConflict;
  /** Destination folder (null = Drive root). */
  folderId: string | null;
}

// ── Service payloads ────────────────────────────────────────────────────────

export interface CreateFolderPayload {
  parentId: string | null;
  name: string;
}

export interface RenamePayload {
  name: string;
}

export interface MovePayload {
  /** Destination folder; null = Drive root. */
  targetFolderId: string | null;
}

/** What the upload call carries besides the bytes (multipart in the real svc). */
export interface UploadOptions {
  folderId: string | null;
  attachmentTypeId?: string | null;
  /** When retrying past a 409, the chosen resolution. */
  conflict?: ConflictMode;
}

/** A successful upload result (the created/updated file). */
export interface UploadResult {
  file: FileRow;
}

/** Request to start a bulk/folder ZIP download - any mix of files + folders
 * (each folder contributes its whole subtree). */
export interface ZipRequest {
  fileIds?: string[];
  folderIds?: string[];
}

// ── Sharing (slice-05, Google-Drive model) ──────────────────────────────────

export type ShareTargetKind = 'file' | 'folder';
/** The tier BEYOND the named-people list on the one stable link. */
export type ShareGeneralAccess = 'restricted' | 'workspace' | 'public';
export type ShareCapability = 'view' | 'edit';

/** A named person on a share ("People with access"), each with their own role. */
export interface ShareUser {
  id: string;
  name?: string | null;
  email?: string | null;
  capability?: ShareCapability;
}

/** The ONE stable share for a target. `url` is the single copyable link; it
 * never changes when access is edited (Google model). */
export interface ShareRow {
  id: string;
  targetKind: ShareTargetKind;
  targetId: string;
  targetName?: string | null;
  generalAccess: ShareGeneralAccess;
  /** Role for the general-access tier. */
  capability: ShareCapability;
  token: string;
  url: string;
  expiresAt: string | null;
  isExpired: boolean;
  hasPassword: boolean;
  maxUploads?: number | null;
  maxTotalMb?: number | null;
  isDisabled: boolean;
  people: ShareUser[];
  createdBy?: string | null;
  createdByName?: string | null;
  createdAt: string;
}

/** In-place edit of the stable share. Only provided fields apply; `expiresAt`/
 * `password` null = clear, omitted = unchanged; `people` (when present) replaces
 * the whole allow-list. */
export interface ShareUpdatePayload {
  generalAccess?: ShareGeneralAccess;
  capability?: ShareCapability;
  expiresAt?: string | null;
  password?: string | null;
  maxUploads?: number | null;
  maxTotalMb?: number | null;
  people?: { userId: string; capability: ShareCapability }[];
  isDisabled?: boolean;
}

/** One root shared TO the current user - the "Shared with me" drive. */
export interface SharedWithMeItem {
  token: string;
  targetKind: ShareTargetKind;
  targetId: string;
  name: string;
  capability: ShareCapability;
  ownerName?: string | null;
  sharedAt: string;
}

// ── Public / scoped share surface ────────────────────────────────────────────

export type PublicShareState =
  | 'open'
  | 'password_required'
  | 'closed'
  | 'sign_in_required';

export interface PublicShareFileNode {
  id: string;
  name: string;
  mime: string;
  sizeBytes: number;
  previewKind: PreviewKind;
}

export interface PublicShareFolderNode {
  id: string;
  name: string;
}

/** The public state envelope (uniform-404 for unknown/disabled/over-ceiling). */
export interface PublicShareView {
  state: PublicShareState;
  message?: string | null;
  tenantName?: string | null;
  kind?: ShareTargetKind | null;
  capability?: ShareCapability | null;
  title?: string | null;
  file?: PublicShareFileNode | null;
  folderId?: string | null;
  breadcrumb: PublicShareFolderNode[];
  folders: PublicShareFolderNode[];
  files: PublicShareFileNode[];
  honeypotField?: string | null;
}

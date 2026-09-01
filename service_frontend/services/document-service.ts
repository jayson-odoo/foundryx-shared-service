/**
 * Document service - the boundary the Drive UI talks to (UI → hook → service →
 * api-client). Phase A points at the in-memory mock; Phase B swaps the export
 * to `realDocumentService` (one line). See sprint-3/04-document-mgmt-drive.md.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  AttachmentTypeRow,
  CreateFolderPayload,
  DocumentSettings,
  DownloadJob,
  FileRow,
  FileVersionRow,
  FolderListing,
  FolderRow,
  MovePayload,
  PublicShareView,
  RenamePayload,
  ShareRow,
  SharedWithMeItem,
  ShareTargetKind,
  ShareUpdatePayload,
  ShareUser,
  UploadConflict,
  UploadOptions,
  UploadResult,
  ZipRequest,
} from '@/types/documents';
import { realDocumentService } from './document-service.real';

/**
 * A same-name file already lives in the destination folder. The UI offers
 * Replace (→ new version) or Keep both (→ auto-renamed copy); retry the upload
 * with `options.conflict` set. Mirrors the backend 409 contract (D5).
 */
export class UploadConflictError extends Error {
  conflict: UploadConflict;

  constructor(conflict: UploadConflict) {
    super(`"${conflict.fileName}" already exists here.`);
    this.name = 'UploadConflictError';
    this.conflict = conflict;
  }
}

/** Upload refused - the tenant storage quota would be exceeded (413, D12). */
export class StorageQuotaError extends Error {
  constructor(message = 'Storage quota exceeded.') {
    super(message);
    this.name = 'StorageQuotaError';
  }
}

/** Upload refused - the file type/size failed the sniff floor or type policy. */
export class UploadRejectedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UploadRejectedError';
  }
}

/** Progress callback for an in-flight upload (0-100). */
export type UploadProgress = (percent: number) => void;

export interface DocumentService {
  // ── Drive navigation ──
  listFolder(folderId: string | null): Promise<FolderListing>;

  // ── Folder ops ──
  createFolder(payload: CreateFolderPayload): Promise<FolderRow>;
  renameFolder(id: string, payload: RenamePayload): Promise<FolderRow>;
  moveFolders(ids: string[], payload: MovePayload): Promise<void>;
  deleteFolders(ids: string[]): Promise<void>;

  // ── File ops ──
  renameFile(id: string, payload: RenamePayload): Promise<FileRow>;
  moveFiles(ids: string[], payload: MovePayload): Promise<void>;
  deleteFiles(ids: string[]): Promise<void>;
  fileVersions(fileId: string): Promise<FileVersionRow[]>;

  /**
   * Upload one file's bytes. Throws {@link UploadConflictError} on a name
   * collision (unless `options.conflict` resolves it), {@link StorageQuotaError}
   * on quota, {@link UploadRejectedError} on a type/size violation.
   */
  upload(
    file: File,
    options: UploadOptions,
    onProgress?: UploadProgress,
  ): Promise<UploadResult>;

  // ── Trash ──
  listTrash(): Promise<{ folders: FolderRow[]; files: FileRow[] }>;
  restoreFolders(ids: string[]): Promise<void>;
  restoreFiles(ids: string[]): Promise<void>;
  purgeFolders(ids: string[]): Promise<void>;
  purgeFiles(ids: string[]): Promise<void>;

  // ── Preview + download ──
  /** A short-lived URL/object-URL for inline preview (image/PDF). */
  previewUrl(fileId: string): Promise<string>;
  /** Direct single-file download (blob). */
  downloadFile(fileId: string): Promise<Blob>;
  /** Kick off an async ZIP of a folder subtree or an explicit file set. */
  requestZip(req: ZipRequest): Promise<DownloadJob>;
  listDownloadJobs(): Promise<DownloadJob[]>;
  /** Fresh signed URL for a ready ZIP job. */
  downloadJobUrl(jobId: string): Promise<{ url: string; filename: string }>;

  // ── Attachment types (Resource shell) ──
  listTypes(query: ListQuery): Promise<ListResult<AttachmentTypeRow>>;
  exportTypes(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
  getType(id: string): Promise<AttachmentTypeRow>;
  createType(
    payload: Omit<AttachmentTypeRow, 'id' | 'fileCount' | 'createdAt' | 'updatedAt'>,
  ): Promise<AttachmentTypeRow>;
  updateType(
    id: string,
    payload: Partial<
      Omit<AttachmentTypeRow, 'id' | 'fileCount' | 'createdAt' | 'updatedAt'>
    >,
  ): Promise<AttachmentTypeRow>;
  deleteType(id: string): Promise<void>;

  // ── Settings ──
  getSettings(): Promise<DocumentSettings>;
  updateSettings(patch: Partial<DocumentSettings>): Promise<DocumentSettings>;

  // ── Sharing (slice-05, Google model) ──
  /** The ONE active share for a target, or null (the dialog calls ensureShare). */
  getTargetShare(kind: ShareTargetKind, id: string): Promise<ShareRow | null>;
  /** Get-or-create the stable share for a target (opening the Share dialog). */
  ensureShare(kind: ShareTargetKind, id: string): Promise<ShareRow>;
  /** Edit access/people/expiry/password/caps in place (server gates may 403/422). */
  updateShare(id: string, patch: ShareUpdatePayload): Promise<ShareRow>;
  /** Hard-disable (oversight kill-switch). */
  revokeShares(ids: string[]): Promise<void>;
  /** Roots shared TO the current user (the "Shared with me" drive). */
  listSharedWithMe(): Promise<SharedWithMeItem[]>;
  /** Same-tenant users for the `tier=user` allow-list MultiSelect. */
  listShareUsers(search?: string): Promise<ShareUser[]>;
  /** Oversight Resource list (Active|Revoked segments). */
  listShares(query: ListQuery, segment: 'active' | 'revoked'): Promise<ListResult<ShareRow>>;
  exportShares(query: ListQuery, columns: string[], segment: 'active' | 'revoked'): Promise<string>;

  /**
   * Resolve a share as the AUTHENTICATED caller (internal/user tiers - opened
   * by any tenant member). 404 → null; a 403 ApiError signals "wrong tenant /
   * not on the allow-list" (the public page renders a denied state).
   */
  resolveShareByToken(token: string, folderId?: string | null): Promise<PublicShareView | null>;
  /** Authed share-scoped preview blob URL (workspace/named-people serve). */
  shareFileBlobUrl(token: string, fileId: string): Promise<string>;
  /** Authed share-scoped download. */
  downloadShareFile(token: string, fileId: string, name: string): Promise<void>;
  /** Authed editor upload into a shared folder (the in-app scoped view). */
  uploadShareFile(token: string, file: File, folderId?: string | null): Promise<void>;
}

/** Phase B → real backend (sprint-3/04). The mock stays importable for unit
 * tests (`document-service.mock.test.ts`) and to drop back to during UI work. */
export const documentService: DocumentService = realDocumentService;

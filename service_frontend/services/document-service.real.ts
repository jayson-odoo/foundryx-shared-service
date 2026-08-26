/**
 * Real document service (Phase B) - talks to FastAPI via the shared api-client.
 * Endpoints follow plan sprint-3/04 §API. Error contracts: upload 409 carries
 * `{fileName, existingFileId}` → UploadConflictError; 413 → StorageQuotaError;
 * 415/422 (type/size) → UploadRejectedError.
 *
 * NOT wired in Phase A - `document-service.ts` exports the mock. Swap the
 * boundary export to `realDocumentService` in Phase B (one line).
 */
import { getSession } from 'next-auth/react';
import { ApiError, apiFetch, apiFetchBlob } from '@/lib/api-client';
import type { ListQuery } from '@/types/resource';
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
  UploadOptions,
  UploadResult,
  ZipRequest,
} from '@/types/documents';
import type { ListResult } from '@/types/resource';
import {
  StorageQuotaError,
  UploadConflictError,
  UploadRejectedError,
  type DocumentService,
  type UploadProgress,
} from './document-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

const BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

export const realDocumentService: DocumentService = {
  listFolder(folderId) {
    const q = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : '';
    return apiFetch<FolderListing>(`/documents/folders${q}`);
  },

  createFolder(payload: CreateFolderPayload) {
    return apiFetch<FolderRow>('/documents/folders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  renameFolder(id, payload: RenamePayload) {
    return apiFetch<FolderRow>(`/documents/folders/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async moveFolders(ids, payload: MovePayload) {
    await apiFetch('/documents/folders/move', {
      method: 'POST',
      body: JSON.stringify({ ids, ...payload }),
    });
  },

  async deleteFolders(ids) {
    await apiFetch('/documents/folders/delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  renameFile(id, payload: RenamePayload) {
    return apiFetch<FileRow>(`/documents/files/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async moveFiles(ids, payload: MovePayload) {
    await apiFetch('/documents/files/move', {
      method: 'POST',
      body: JSON.stringify({ ids, ...payload }),
    });
  },

  async deleteFiles(ids) {
    await apiFetch('/documents/files/delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  fileVersions(fileId) {
    return apiFetch<FileVersionRow[]>(`/documents/files/${fileId}/versions`);
  },

  async upload(file: File, options: UploadOptions, onProgress?: UploadProgress) {
    // XHR (not fetch) so we get real upload progress events for the drawer.
    const form = new FormData();
    form.append('file', file);
    form.append('folder_id', options.folderId ?? '');
    if (options.attachmentTypeId) form.append('attachment_type_id', options.attachmentTypeId);
    if (options.conflict) form.append('on_conflict', options.conflict);

    const session = await getSession();
    const token = session?.accessToken ?? null;

    return new Promise<UploadResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/documents/files`);
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve({ file: JSON.parse(xhr.responseText) as FileRow });
          return;
        }
        let detail: unknown;
        try {
          detail = JSON.parse(xhr.responseText)?.detail;
        } catch {
          detail = undefined;
        }
        if (xhr.status === 409) {
          const d = detail as { fileName?: string; existingFileId?: string } | undefined;
          reject(
            new UploadConflictError({
              fileName: d?.fileName ?? file.name,
              existingFileId: d?.existingFileId ?? '',
            }),
          );
        } else if (xhr.status === 413) {
          reject(new StorageQuotaError(typeof detail === 'string' ? detail : undefined));
        } else if (xhr.status === 415 || xhr.status === 422) {
          reject(new UploadRejectedError(typeof detail === 'string' ? detail : 'File rejected.'));
        } else {
          reject(new ApiError(`Upload failed (${xhr.status})`, xhr.status, null, detail));
        }
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(form);
    });
  },

  listTrash() {
    return apiFetch<{ folders: FolderRow[]; files: FileRow[] }>('/documents/trash');
  },

  async restoreFolders(ids) {
    await apiFetch('/documents/folders/restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  async restoreFiles(ids) {
    await apiFetch('/documents/files/restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  async purgeFolders(ids) {
    await apiFetch('/documents/folders/purge', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  async purgeFiles(ids) {
    await apiFetch('/documents/files/purge', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  async previewUrl(fileId) {
    const blob = await apiFetchBlob(`/documents/files/${fileId}/content?disposition=inline`);
    return URL.createObjectURL(blob);
  },

  downloadFile(fileId) {
    return apiFetchBlob(`/documents/files/${fileId}/content?disposition=attachment`);
  },

  requestZip(req: ZipRequest) {
    return apiFetch<DownloadJob>('/documents/download-jobs', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  },

  listDownloadJobs() {
    return apiFetch<DownloadJob[]>('/documents/download-jobs');
  },

  async downloadJobUrl(jobId) {
    // The ready ZIP streams from an authed route (an <a href> can't carry the
    // Bearer) → fetch it as a blob and hand back an object URL. The caller
    // supplies the real filename from its own job list.
    const blob = await apiFetchBlob(`/documents/download-jobs/${jobId}/content`);
    return { url: URL.createObjectURL(blob), filename: 'download.zip' };
  },

  listTypes(query) {
    return apiFetch(`/documents/types?${listParams(query).toString()}`);
  },

  exportTypes(query, columns, ids) {
    const p = listParams(query);
    p.set('columns', columns.join(','));
    if (ids?.length) p.set('ids', ids.join(','));
    return apiFetch<string>(`/documents/types/export?${p.toString()}`);
  },

  getType(id) {
    return apiFetch<AttachmentTypeRow>(`/documents/types/${id}`);
  },

  createType(payload) {
    return apiFetch<AttachmentTypeRow>('/documents/types', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  updateType(id, payload) {
    return apiFetch<AttachmentTypeRow>(`/documents/types/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async deleteType(id) {
    await apiFetch(`/documents/types/${id}`, { method: 'DELETE' });
  },

  getSettings() {
    return apiFetch<DocumentSettings>('/documents/settings');
  },

  updateSettings(patch) {
    return apiFetch<DocumentSettings>('/documents/settings', {
      method: 'PUT',
      body: JSON.stringify(patch),
    });
  },

  // ── Sharing (slice-05, Google model) ──

  getTargetShare(kind: ShareTargetKind, id: string) {
    return apiFetch<ShareRow | null>(
      `/documents/shares/target?kind=${kind}&id=${encodeURIComponent(id)}`,
    );
  },

  ensureShare(kind: ShareTargetKind, id: string) {
    return apiFetch<ShareRow>('/documents/shares/ensure', {
      method: 'POST',
      body: JSON.stringify({ targetKind: kind, targetId: id }),
    });
  },

  updateShare(id: string, patch: ShareUpdatePayload) {
    return apiFetch<ShareRow>(`/documents/shares/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  async revokeShares(ids: string[]) {
    await apiFetch('/documents/shares/revoke', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  listSharedWithMe() {
    return apiFetch<SharedWithMeItem[]>('/documents/shared-with-me');
  },

  listShareUsers(search?: string) {
    const q = search ? `?search=${encodeURIComponent(search)}` : '';
    return apiFetch<ShareUser[]>(`/documents/shares/users${q}`);
  },

  listShares(query, segment): Promise<ListResult<ShareRow>> {
    const p = listParams(query);
    p.set('segment', segment);
    return apiFetch(`/documents/shares?${p.toString()}`);
  },

  exportShares(query, columns, segment) {
    const p = listParams(query);
    p.set('segment', segment);
    p.set('columns', columns.join(','));
    return apiFetch<string>(`/documents/shares/export?${p.toString()}`);
  },

  async resolveShareByToken(token, folderId) {
    const q = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : '';
    try {
      return await apiFetch<PublicShareView>(
        `/documents/shares/by-token/${encodeURIComponent(token)}${q}`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  async shareFileBlobUrl(token, fileId) {
    const blob = await apiFetchBlob(
      `/documents/shares/by-token/${encodeURIComponent(token)}/file/${encodeURIComponent(fileId)}?disposition=inline`,
    );
    return URL.createObjectURL(blob);
  },

  async downloadShareFile(token, fileId, name) {
    const blob = await apiFetchBlob(
      `/documents/shares/by-token/${encodeURIComponent(token)}/file/${encodeURIComponent(fileId)}?disposition=attachment`,
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  },

  async uploadShareFile(token, file, folderId) {
    const form = new FormData();
    form.append('file', file);
    form.append('folder_id', folderId ?? '');
    const session = await getSession();
    const tk = session?.accessToken ?? null;
    const res = await fetch(
      `${BASE_URL}/documents/shares/by-token/${encodeURIComponent(token)}/upload`,
      { method: 'POST', body: form, headers: tk ? { Authorization: `Bearer ${tk}` } : {} },
    );
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json())?.detail;
      } catch {
        detail = undefined;
      }
      throw new ApiError(
        typeof detail === 'string' ? detail : `Upload failed (${res.status})`,
        res.status,
        null,
        detail,
      );
    }
  },
};

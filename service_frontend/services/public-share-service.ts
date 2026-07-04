/**
 * Public (pre-auth) document-share service (plan sprint-3/05, D9). NO auth —
 * the token is the bearer capability. Resolve returns the state envelope
 * (uniform 404 → null); unlock + upload ride the backend's own `doc_share`
 * throttle. File bytes are fetched as blobs (so a password header can ride the
 * request — an `<img src>` can't carry it) and served object-URLs.
 */
import { ApiError, publicFetch } from '@/lib/api-client';
import type { PublicShareView } from '@/types/documents';

const BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

function pwHeaders(password?: string | null): HeadersInit {
  return password ? { 'X-Share-Password': password } : {};
}

export interface PublicShareService {
  resolve(token: string, folderId?: string | null): Promise<PublicShareView | null>;
  unlock(token: string, password: string, folderId?: string | null): Promise<PublicShareView>;
  fileBlobUrl(token: string, fileId: string, password?: string | null): Promise<string>;
  download(token: string, fileId: string, name: string, password?: string | null): Promise<void>;
  upload(
    token: string,
    file: File,
    opts: { folderId?: string | null; honeypotField?: string | null; password?: string | null },
    onProgress?: (pct: number) => void,
  ): Promise<void>;
}

export const publicShareService: PublicShareService = {
  async resolve(token, folderId) {
    const q = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : '';
    try {
      return await publicFetch<PublicShareView>(
        `/public/documents/${encodeURIComponent(token)}${q}`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  async unlock(token, password, folderId) {
    const q = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : '';
    return publicFetch<PublicShareView>(
      `/public/documents/${encodeURIComponent(token)}/unlock${q}`,
      { method: 'POST', body: JSON.stringify({ password }) },
    );
  },

  async fileBlobUrl(token, fileId, password) {
    const res = await fetch(
      `${BASE_URL}/public/documents/${encodeURIComponent(token)}/file/${encodeURIComponent(fileId)}?disposition=inline`,
      { headers: pwHeaders(password) },
    );
    if (!res.ok) throw new ApiError(`Fetch failed (${res.status})`, res.status, null, null);
    return URL.createObjectURL(await res.blob());
  },

  async download(token, fileId, name, password) {
    const res = await fetch(
      `${BASE_URL}/public/documents/${encodeURIComponent(token)}/file/${encodeURIComponent(fileId)}?disposition=attachment`,
      { headers: pwHeaders(password) },
    );
    if (!res.ok) throw new ApiError(`Download failed (${res.status})`, res.status, null, null);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  },

  upload(token, file, opts, onProgress) {
    const form = new FormData();
    form.append('file', file);
    form.append('folder_id', opts.folderId ?? '');
    if (opts.honeypotField) form.append(opts.honeypotField, ''); // a real user leaves it empty

    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/public/documents/${encodeURIComponent(token)}/upload`);
      if (opts.password) xhr.setRequestHeader('X-Share-Password', opts.password);
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
          return;
        }
        let detail: unknown;
        try {
          detail = JSON.parse(xhr.responseText)?.detail;
        } catch {
          detail = undefined;
        }
        reject(
          new ApiError(
            typeof detail === 'string' ? detail : `Upload failed (${xhr.status})`,
            xhr.status,
            null,
            detail,
          ),
        );
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(form);
    });
  },
};

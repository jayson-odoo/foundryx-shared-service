/**
 * Real avatar service — multipart to the plan-06 endpoints. Bound in Phase B
 * (one-line swap in avatar-service.ts).
 */
import { apiFetch } from '@/lib/api-client';
import type { AvatarResult, AvatarService } from './avatar-service';

function upload(path: string, blob: Blob): Promise<AvatarResult> {
  const form = new FormData();
  // Filename is cosmetic — the backend sniffs magic bytes, never trusts it.
  form.append('file', blob, 'avatar');
  return apiFetch<AvatarResult>(path, { method: 'POST', body: form });
}

export const realAvatarService: AvatarService = {
  uploadSelf: (blob) => upload('/me/avatar', blob),
  removeSelf: () => apiFetch<AvatarResult>('/me/avatar', { method: 'DELETE' }),
  upload: (userId, blob) => upload(`/users/${userId}/avatar`, blob),
  remove: (userId) =>
    apiFetch<AvatarResult>(`/users/${userId}/avatar`, { method: 'DELETE' }),
};

'use client';

/**
 * Document-share access for the two share surfaces (plan sprint-3/05, Google
 * model):
 *
 *  - PUBLIC mode (`/public/documents/{token}`, anonymous) - resolves a
 *    public-tier link. A workspace/restricted link returns `sign_in_required`;
 *    the page then routes a logged-in member to the in-app scoped view, or shows
 *    a sign-in CTA. Password gate + anonymous upload ride here.
 *  - AUTHED mode (`/documents/shared/{token}`, `preferAuthed`) - resolves the
 *    link as the signed-in member via the authed by-token route (workspace /
 *    named-people). 403 = no access; serves + edits ride the authed endpoints.
 *
 * The unlocked password (public mode) lives in memory only; file fetch/download/
 * upload route by mode so the right sandboxed endpoint is hit each time.
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { documentService } from '@/services/document-service';
import { publicShareService } from '@/services/public-share-service';
import type { PublicShareView } from '@/types/documents';

type Mode = 'public' | 'authed';

export interface UsePublicShare {
  view: PublicShareView | null;
  loading: boolean;
  notFound: boolean;
  forbidden: boolean;
  mode: Mode;
  needsPassword: boolean;
  signInRequired: boolean;
  unlocking: boolean;
  passwordError: string | null;
  uploading: boolean;
  uploadError: string | null;
  uploadDone: boolean;
  canUpload: boolean;
  unlock: (password: string) => Promise<void>;
  navigate: (folderId: string | null) => Promise<void>;
  download: (fileId: string, name: string) => Promise<void>;
  previewUrl: (fileId: string) => Promise<string>;
  upload: (file: File) => Promise<void>;
}

export function usePublicShare(
  token: string,
  opts: { preferAuthed?: boolean } = {},
): UsePublicShare {
  const mode: Mode = opts.preferAuthed ? 'authed' : 'public';
  const [view, setView] = useState<PublicShareView | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [password, setPassword] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadDone, setUploadDone] = useState(false);

  const needsPassword = view?.state === 'password_required';
  const signInRequired = view?.state === 'sign_in_required';

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        if (mode === 'authed') {
          const v = await documentService.resolveShareByToken(token);
          if (cancelled) return;
          if (v === null) setNotFound(true);
          else setView(v);
        } else {
          const v = await publicShareService.resolve(token);
          if (cancelled) return;
          if (v === null) setNotFound(true);
          else setView(v);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else setNotFound(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, mode]);

  const unlock = useCallback(
    async (pw: string) => {
      setUnlocking(true);
      setPasswordError(null);
      try {
        const v = await publicShareService.unlock(token, pw);
        setPassword(pw);
        setView(v);
      } catch (e) {
        setPasswordError(
          e instanceof ApiError && e.status === 429
            ? 'Too many attempts. Please wait a moment and try again.'
            : 'Incorrect password.',
        );
      } finally {
        setUnlocking(false);
      }
    },
    [token],
  );

  const navigate = useCallback(
    async (folderId: string | null) => {
      setLoading(true);
      try {
        let v: PublicShareView | null;
        if (mode === 'authed') {
          v = await documentService.resolveShareByToken(token, folderId);
        } else if (password) {
          v = await publicShareService.unlock(token, password, folderId);
        } else {
          v = await publicShareService.resolve(token, folderId);
        }
        if (v === null) setNotFound(true);
        else setView(v);
      } finally {
        setLoading(false);
      }
    },
    [token, password, mode],
  );

  const download = useCallback(
    (fileId: string, name: string) =>
      mode === 'authed'
        ? documentService.downloadShareFile(token, fileId, name)
        : publicShareService.download(token, fileId, name, password),
    [token, password, mode],
  );

  const previewUrl = useCallback(
    (fileId: string) =>
      mode === 'authed'
        ? documentService.shareFileBlobUrl(token, fileId)
        : publicShareService.fileBlobUrl(token, fileId, password),
    [token, password, mode],
  );

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      setUploadDone(false);
      try {
        if (mode === 'authed') {
          await documentService.uploadShareFile(token, file, view?.folderId ?? null);
        } else {
          await publicShareService.upload(token, file, {
            folderId: view?.folderId ?? null,
            honeypotField: view?.honeypotField,
            password,
          });
        }
        setUploadDone(true);
        // Re-list the current folder so the new file appears.
        let v: PublicShareView | null;
        if (mode === 'authed') v = await documentService.resolveShareByToken(token, view?.folderId ?? null);
        else if (password) v = await publicShareService.unlock(token, password, view?.folderId ?? null);
        else v = await publicShareService.resolve(token, view?.folderId ?? null);
        if (v) setView(v);
      } catch (e) {
        setUploadError(e instanceof ApiError ? e.message : 'Upload failed.');
      } finally {
        setUploading(false);
      }
    },
    [token, password, mode, view?.folderId, view?.honeypotField],
  );

  const canUpload =
    view?.state === 'open' && view?.capability === 'edit' && view?.kind === 'folder';

  return {
    view,
    loading,
    notFound,
    forbidden,
    mode,
    needsPassword: !!needsPassword,
    signInRequired: !!signInRequired,
    unlocking,
    passwordError,
    uploading,
    uploadError,
    uploadDone,
    canUpload,
    unlock,
    navigate,
    download,
    previewUrl,
    upload,
  };
}

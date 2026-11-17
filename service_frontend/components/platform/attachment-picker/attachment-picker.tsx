'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';
import { FileText, Paperclip, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { isCommentPostResult } from '@/lib/upload-files';

export const MAX_FILES = 10;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;

export interface AttachmentDraftWrapperProps {
  onPaste: (e: ClipboardEvent<HTMLElement>) => void;
  onDrop: (e: DragEvent<HTMLElement>) => void;
  onDragOver: (e: DragEvent<HTMLElement>) => void;
}

export interface AttachmentDraft {
  files: File[];
  error: string | null;
  add: (incoming: FileList | File[]) => void;
  remove: (index: number) => void;
  clear: () => void;
  /** Keep exactly these files (e.g. only the ones that failed to upload). */
  replace: (files: File[]) => void;
  /** Remove the files just sent (keeping `keep` first); later additions stay. */
  discard: (sent: File[], keep?: File[]) => void;
  /** Spread on the form / composer so paste and drop land in this draft. */
  wrapperProps: AttachmentDraftWrapperProps;
}

const hasFiles = (dt: DataTransfer | null | undefined): boolean =>
  Boolean(dt && (dt.files?.length || Array.from(dt.types ?? []).includes('Files')));

/** Pending (not yet uploaded) files for one form / composer: pick, paste, drop,
 * with the 10 files / 25 MB limits. */
export function useAttachmentDraft(): AttachmentDraft {
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);

  const add = useCallback((incoming: FileList | File[]) => {
    const list = Array.from(incoming);
    if (list.length === 0) return;
    setError(null);
    setFiles((prev) => {
      const next = [...prev];
      let message: string | null = null;
      for (const file of list) {
        if (file.size > MAX_FILE_BYTES) {
          message = `${file.name} is too large (max 25 MB)`;
        } else if (next.length >= MAX_FILES) {
          message = `Up to ${MAX_FILES} files`;
        } else {
          next.push(file);
        }
      }
      if (message) setError(message);
      return next;
    });
  }, []);

  const remove = useCallback((index: number) => {
    setError(null);
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clear = useCallback(() => {
    setError(null);
    setFiles([]);
  }, []);

  const replace = useCallback((next: File[]) => {
    setError(null);
    setFiles(next);
  }, []);

  /** Drop exactly the files just sent, keeping `keep` (those that failed)
   * first; files added while the post was sending stay. */
  const discard = useCallback((sent: File[], keep: File[] = []) => {
    const gone = new Set(sent);
    setFiles((prev) => [...keep, ...prev.filter((f) => !gone.has(f))]);
  }, []);

  const wrapperProps = useMemo<AttachmentDraftWrapperProps>(
    () => ({
      onPaste: (e) => {
        const pasted = e.clipboardData?.files;
        if (pasted && pasted.length > 0) {
          // A paste with text AND an image (Word) keeps its text; the image is
          // still added. Only a files-only paste is taken over.
          const text = typeof e.clipboardData.getData === 'function' ? e.clipboardData.getData('text/plain') : '';
          if (!text) e.preventDefault();
          add(pasted);
        }
      },
      onDrop: (e) => {
        if (!hasFiles(e.dataTransfer)) return;
        e.preventDefault();
        add(e.dataTransfer.files);
      },
      onDragOver: (e) => {
        if (hasFiles(e.dataTransfer)) e.preventDefault();
      },
    }),
    [add],
  );

  return { files, error, add, remove, clear, replace, discard, wrapperProps };
}

/** Object URLs for image previews, revoked on remove / unmount. */
function useImagePreviews(files: File[]): (string | null)[] {
  const cache = useRef(new Map<File, string>());
  const urls = files.map((f) => {
    if (!f.type.startsWith('image/') || typeof URL.createObjectURL !== 'function') return null;
    let url = cache.current.get(f);
    if (!url) {
      url = URL.createObjectURL(f);
      cache.current.set(f, url);
    }
    return url;
  });
  useEffect(() => {
    const live = new Set(files);
    cache.current.forEach((url, file) => {
      if (!live.has(file)) {
        URL.revokeObjectURL(url);
        cache.current.delete(file);
      }
    });
  }, [files]);
  useEffect(() => {
    const map = cache.current;
    return () => {
      map.forEach((url) => URL.revokeObjectURL(url));
      map.clear();
    };
  }, []);
  return urls;
}

/** Paperclip + pending files as small thumbnails with Remove. */
export function AttachmentPicker({ draft }: { draft: AttachmentDraft }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const previews = useImagePreviews(draft.files);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="image/*,video/*,audio/*,application/pdf,*/*"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) draft.add(e.target.files);
            e.target.value = '';
          }}
        />
        <Button type="button" variant="outline" size="sm" aria-label="Attach files" onClick={() => inputRef.current?.click()}>
          <Paperclip className="size-4" aria-hidden />
        </Button>
        {draft.error && <p className="text-sm text-destructive">{draft.error}</p>}
      </div>
      {draft.files.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {draft.files.map((file, i) => (
            <li key={`${file.name}-${i}`} className="relative w-20">
              <div className="flex size-20 items-center justify-center overflow-hidden rounded-md border bg-muted/30">
                {previews[i] ? (
                  <img src={previews[i] as string} alt="" className="size-full object-cover" />
                ) : (
                  <FileText className="size-6 text-muted-foreground" aria-hidden />
                )}
              </div>
              <ClampedText text={file.name} lines={1} className="mt-1 text-2xs text-muted-foreground" />
              <button
                type="button"
                aria-label={`Remove ${file.name}`}
                onClick={() => draft.remove(i)}
                className={`${PRESSED_CLASS} absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full border bg-background shadow-sm hover:text-destructive`}
              >
                <X className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A posted comment whose files did not all upload: what is left to retry. */
export interface PendingUploads {
  commentId: string;
  failed: File[];
}

/**
 * After a comment is posted, keep the files that failed in the draft and offer
 * a retry against the SAME comment. `track` takes whatever the post resolved to.
 */
export function useUploadRetry(
  draft: AttachmentDraft,
  retry?: (commentId: string, files: File[]) => Promise<File[]>,
) {
  const [pending, setPending] = useState<PendingUploads | null>(null);
  const [busy, setBusy] = useState(false);
  const { clear, replace, discard } = draft;

  /** `sent` = the files that went out with the post: only those leave the
   * draft, so anything added while the post was sending is kept. */
  const track = useCallback(
    (result: unknown, sent?: File[]) => {
      if (isCommentPostResult(result) && result.failed.length > 0) {
        setPending({ commentId: result.commentId, failed: result.failed });
        if (sent) discard(sent, result.failed);
        else replace(result.failed);
      } else {
        setPending(null);
        if (sent) discard(sent);
        else clear();
      }
    },
    [clear, replace, discard],
  );

  const retryNow = useCallback(async () => {
    if (!pending || !retry) return;
    setBusy(true);
    try {
      const failed = await retry(pending.commentId, pending.failed);
      if (failed.length > 0) {
        setPending({ commentId: pending.commentId, failed });
        replace(failed);
      } else {
        setPending(null);
        clear();
      }
    } finally {
      setBusy(false);
    }
  }, [pending, retry, clear, replace]);

  return { pending, busy, track, retryNow };
}

/** Names the files that did not upload, with the one button to retry them. */
export function UploadRetryNotice({
  pending,
  busy,
  onRetry,
}: {
  pending: PendingUploads;
  busy: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="text-sm text-destructive">Could not upload {pending.failed.map((f) => f.name).join(', ')}.</p>
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

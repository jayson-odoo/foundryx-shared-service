'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';
import { FileText, Paperclip, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';

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

  const wrapperProps = useMemo<AttachmentDraftWrapperProps>(
    () => ({
      onPaste: (e) => {
        const pasted = e.clipboardData?.files;
        if (pasted && pasted.length > 0) {
          e.preventDefault();
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

  return { files, error, add, remove, clear, wrapperProps };
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

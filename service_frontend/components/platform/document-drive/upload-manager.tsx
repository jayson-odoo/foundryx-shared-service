'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { documentService } from '@/services/document-service';
import {
  StorageQuotaError,
  UploadConflictError,
  UploadRejectedError,
} from '@/services/document-service';
import type { ConflictMode, UploadFileItem } from '@/types/documents';

interface EnqueueOptions {
  folderId: string | null;
  attachmentTypeId?: string | null;
}

interface UploadManagerValue {
  items: UploadFileItem[];
  /** In-flight (queued/uploading/conflict) count - for the badge. */
  activeCount: number;
  open: boolean;
  /** Bumps whenever an upload completes successfully - Drive watches to reload. */
  completedVersion: number;
  setOpen: (open: boolean) => void;
  enqueue: (files: File[], options: EnqueueOptions) => void;
  resolveConflict: (itemId: string, mode: ConflictMode) => void;
  retry: (itemId: string) => void;
  remove: (itemId: string) => void;
  clearFinished: () => void;
}

const UploadManagerContext = createContext<UploadManagerValue | null>(null);

let counter = 0;
const newId = () => `up_${(counter += 1)}`;

export function UploadManagerProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<UploadFileItem[]>([]);
  const [open, setOpen] = useState(false);
  const [completedVersion, setCompletedVersion] = useState(0);
  // File objects can't live in state - keep them in a ref keyed by item id.
  const filesRef = useRef<Map<string, File>>(new Map());
  const optsRef = useRef<Map<string, EnqueueOptions>>(new Map());

  const patch = useCallback((id: string, next: Partial<UploadFileItem>) => {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...next } : it)));
  }, []);

  const run = useCallback(
    async (id: string, conflict?: ConflictMode) => {
      const file = filesRef.current.get(id);
      const opts = optsRef.current.get(id);
      if (!file || !opts) return;
      patch(id, { status: 'uploading', progress: 0, error: undefined });
      try {
        await documentService.upload(
          file,
          { folderId: opts.folderId, attachmentTypeId: opts.attachmentTypeId, conflict },
          (percent) => patch(id, { progress: percent }),
        );
        patch(id, { status: 'done', progress: 100 });
        setCompletedVersion((v) => v + 1);
        filesRef.current.delete(id);
      } catch (error) {
        if (error instanceof UploadConflictError) {
          patch(id, { status: 'conflict', conflict: error.conflict });
        } else if (error instanceof StorageQuotaError) {
          patch(id, { status: 'failed', error: error.message });
        } else if (error instanceof UploadRejectedError) {
          patch(id, { status: 'failed', error: error.message });
        } else {
          patch(id, { status: 'failed', error: 'Upload failed. Try again.' });
        }
      }
    },
    [patch],
  );

  const enqueue = useCallback(
    (files: File[], options: EnqueueOptions) => {
      if (!files.length) return;
      const newItems: UploadFileItem[] = files.map((file) => {
        const id = newId();
        filesRef.current.set(id, file);
        // Defensive copy - a caller that reuses/mutates the same options object
        // across drops must not retarget already-queued uploads' folder/type.
        optsRef.current.set(id, { ...options });
        return {
          id,
          name: file.name,
          sizeBytes: file.size,
          status: 'queued',
          progress: 0,
          folderId: options.folderId,
        };
      });
      setItems((prev) => [...newItems, ...prev]);
      setOpen(true);
      newItems.forEach((it) => void run(it.id));
    },
    [run],
  );

  const resolveConflict = useCallback(
    (itemId: string, mode: ConflictMode) => {
      void run(itemId, mode);
    },
    [run],
  );

  const retry = useCallback((itemId: string) => void run(itemId), [run]);

  const remove = useCallback((itemId: string) => {
    filesRef.current.delete(itemId);
    optsRef.current.delete(itemId);
    setItems((prev) => prev.filter((it) => it.id !== itemId));
  }, []);

  const clearFinished = useCallback(() => {
    setItems((prev) => {
      prev.forEach((it) => {
        if (it.status === 'done' || it.status === 'failed') {
          filesRef.current.delete(it.id);
          optsRef.current.delete(it.id);
        }
      });
      return prev.filter((it) => it.status !== 'done' && it.status !== 'failed');
    });
  }, []);

  const value = useMemo<UploadManagerValue>(
    () => ({
      items,
      activeCount: items.filter(
        (it) => it.status === 'queued' || it.status === 'uploading' || it.status === 'conflict',
      ).length,
      open,
      completedVersion,
      setOpen,
      enqueue,
      resolveConflict,
      retry,
      remove,
      clearFinished,
    }),
    [items, open, completedVersion, enqueue, resolveConflict, retry, remove, clearFinished],
  );

  return (
    <UploadManagerContext.Provider value={value}>{children}</UploadManagerContext.Provider>
  );
}

export function useUploadManager(): UploadManagerValue {
  const ctx = useContext(UploadManagerContext);
  if (!ctx) throw new Error('useUploadManager must be used within UploadManagerProvider');
  return ctx;
}

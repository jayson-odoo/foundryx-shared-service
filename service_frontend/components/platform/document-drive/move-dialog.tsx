'use client';

import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, Folder, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { documentService } from '@/services/document-service';
import type { FolderRow } from '@/types/documents';

export interface MoveDialogProps {
  open: boolean;
  /** Folder ids being moved - excluded as destinations (no self-move). */
  movingFolderIds: string[];
  /** Where the items currently live - disables "Move here" for a no-op. */
  sourceFolderId: string | null;
  onMove: (targetFolderId: string | null) => Promise<void>;
  onClose: () => void;
}

/** Destination picker - descend the tree, then "Move here". */
export function MoveDialog({
  open,
  movingFolderIds,
  sourceFolderId,
  onMove,
  onClose,
}: MoveDialogProps) {
  const [pickerId, setPickerId] = useState<string | null>(null);
  const [folders, setFolders] = useState<FolderRow[]>([]);
  const [crumbs, setCrumbs] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (id: string | null) => {
    setLoading(true);
    try {
      const listing = await documentService.listFolder(id);
      setFolders(listing.folders);
      setCrumbs(listing.breadcrumb);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      setPickerId(null);
      void load(null);
    }
  }, [open, load]);

  const descend = (id: string | null) => {
    setPickerId(id);
    void load(id);
  };

  const moving = new Set(movingFolderIds);
  const sameAsSource = pickerId === sourceFolderId;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Move to…</DialogTitle>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-muted"
            onClick={() => descend(null)}
          >
            <HardDrive className="size-3.5" /> Drive
          </button>
          {crumbs.map((c) => (
            <span key={c.id} className="inline-flex items-center gap-1">
              <ChevronRight className="size-3.5" />
              <button
                type="button"
                className="rounded px-1.5 py-0.5 hover:bg-muted"
                onClick={() => descend(c.id)}
              >
                {c.name}
              </button>
            </span>
          ))}
        </div>

        <ScrollArea className="h-64 rounded-md border">
          <div className="p-1">
            {loading && (
              <div className="space-y-1.5 p-1">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            )}
            {!loading && folders.length === 0 && (
              <div className="p-4 text-sm text-muted-foreground">No sub-folders here.</div>
            )}
            {!loading &&
              folders.map((f) => {
                const disabled = moving.has(f.id);
                return (
                  <button
                    key={f.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => descend(f.id)}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className="flex items-center gap-2 truncate">
                      <Folder className="size-4 text-primary" />
                      <span className="truncate">{f.name}</span>
                    </span>
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </button>
                );
              })}
          </div>
        </ScrollArea>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={busy || sameAsSource}
            onClick={async () => {
              setBusy(true);
              try {
                await onMove(pickerId);
                onClose();
              } finally {
                setBusy(false);
              }
            }}
          >
            Move here
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

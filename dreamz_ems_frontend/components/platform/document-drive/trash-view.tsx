'use client';

import { useCallback, useEffect, useState } from 'react';
import { Folder, RotateCcw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { documentService } from '@/services/document-service';
import type { FileRow, FolderRow } from '@/types/documents';
import type { DriveView } from './drive-grid';
import { fileIcon, formatBytes } from './lib';

export interface TrashViewProps {
  view: DriveView;
  /** Notify the Drive (tree + usage) to refresh after a restore/purge. */
  onChanged: () => void;
}

interface PurgeTargets {
  folderIds: string[];
  fileIds: string[];
}

export function TrashView({ view, onChanged }: TrashViewProps) {
  const [folders, setFolders] = useState<FolderRow[]>([]);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selFolders, setSelFolders] = useState<Set<string>>(new Set());
  const [selFiles, setSelFiles] = useState<Set<string>>(new Set());
  const [purge, setPurge] = useState<PurgeTargets | null>(null);
  const [confirmText, setConfirmText] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const trash = await documentService.listTrash();
      setFolders(trash.folders);
      setFiles(trash.files);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const clearSel = () => {
    setSelFolders(new Set());
    setSelFiles(new Set());
  };
  const count = selFolders.size + selFiles.size;

  const toggleFolder = (id: string) =>
    setSelFolders((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleFile = (id: string) =>
    setSelFiles((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const restore = async (targets: PurgeTargets) => {
    if (targets.folderIds.length) await documentService.restoreFolders(targets.folderIds);
    if (targets.fileIds.length) await documentService.restoreFiles(targets.fileIds);
    clearSel();
    await load();
    onChanged();
  };

  const doPurge = async () => {
    if (!purge) return;
    if (purge.folderIds.length) await documentService.purgeFolders(purge.folderIds);
    if (purge.fileIds.length) await documentService.purgeFiles(purge.fileIds);
    setPurge(null);
    setConfirmText('');
    clearSel();
    await load();
    onChanged();
  };

  const selectionTargets = (): PurgeTargets => ({
    folderIds: Array.from(selFolders),
    fileIds: Array.from(selFiles),
  });

  const empty = folders.length === 0 && files.length === 0;
  const purgeCount = purge ? purge.folderIds.length + purge.fileIds.length : 0;

  return (
    <div className="p-1">
      {count > 0 && (
        <div className="mb-3 flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
          <span className="text-sm">{count} selected</span>
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="outline" onClick={() => void restore(selectionTargets())}>
              <RotateCcw className="size-3.5" /> Restore
            </Button>
            <Button size="sm" variant="destructive" onClick={() => setPurge(selectionTargets())}>
              <Trash2 className="size-3.5" /> Delete forever
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="p-6 text-center text-sm text-muted-foreground">Loading trash…</p>
      ) : empty ? (
        <div className="flex h-56 flex-col items-center justify-center gap-2 text-muted-foreground">
          <Trash2 className="size-10 opacity-40" />
          <p className="text-sm">Trash is empty.</p>
        </div>
      ) : (
        <div
          className={cn(
            view === 'card'
              ? 'grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5'
              : 'flex flex-col rounded-md border',
          )}
        >
          {folders.map((f) => (
            <TrashEntry
              key={f.id}
              view={view}
              name={f.name}
              meta="Folder"
              icon={<Folder className={view === 'card' ? 'size-8 text-primary' : 'size-5 text-primary'} />}
              selected={selFolders.has(f.id)}
              onToggle={() => toggleFolder(f.id)}
              onRestore={() => void restore({ folderIds: [f.id], fileIds: [] })}
              onPurge={() => setPurge({ folderIds: [f.id], fileIds: [] })}
            />
          ))}
          {files.map((f) => {
            const Icon = fileIcon(f.name);
            return (
              <TrashEntry
                key={f.id}
                view={view}
                name={f.name}
                meta={formatBytes(f.currentVersion.sizeBytes)}
                icon={<Icon className={view === 'card' ? 'size-8 text-muted-foreground' : 'size-5 text-muted-foreground'} />}
                selected={selFiles.has(f.id)}
                onToggle={() => toggleFile(f.id)}
                onRestore={() => void restore({ folderIds: [], fileIds: [f.id] })}
                onPurge={() => setPurge({ folderIds: [], fileIds: [f.id] })}
              />
            );
          })}
        </div>
      )}

      <Dialog open={purge !== null} onOpenChange={(o) => !o && setPurge(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete permanently?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This permanently deletes {purgeCount} item{purgeCount === 1 ? '' : 's'} and every
            stored version. This can’t be undone. Type{' '}
            <span className="font-semibold">DELETE</span> to confirm.
          </p>
          <Input
            value={confirmText}
            autoFocus
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="DELETE"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurge(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={confirmText !== 'DELETE'} onClick={() => void doPurge()}>
              Delete forever
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TrashEntry({
  view,
  name,
  meta,
  icon,
  selected,
  onToggle,
  onRestore,
  onPurge,
}: {
  view: DriveView;
  name: string;
  meta: string;
  icon: React.ReactNode;
  selected: boolean;
  onToggle: () => void;
  onRestore: () => void;
  onPurge: () => void;
}) {
  const stopToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle();
  };

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        {view === 'list' ? (
          <div
            data-entry="trash"
            data-name={name}
            className={cn(
              'flex items-center gap-3 border-b px-3 py-2.5 text-sm last:border-b-0',
              selected ? 'bg-primary/10' : 'hover:bg-muted/60',
            )}
          >
            <span onClick={stopToggle}>
              <Checkbox checked={selected} aria-label={`Select ${name}`} />
            </span>
            {icon}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium" title={name}>
                {name}
              </p>
              <p className="text-xs text-muted-foreground">{meta}</p>
            </div>
          </div>
        ) : (
          <div
            data-entry="trash"
            data-name={name}
            className={cn(
              'group relative flex flex-col gap-2 rounded-lg border bg-card p-3',
              selected ? 'border-primary ring-1 ring-primary' : 'hover:border-primary/40',
            )}
          >
            <div className="flex items-start justify-between">
              {icon}
              <span
                onClick={stopToggle}
                className={cn(
                  'transition-opacity',
                  selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
                )}
              >
                <Checkbox checked={selected} aria-label={`Select ${name}`} />
              </span>
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium" title={name}>
                {name}
              </p>
              <p className="text-xs text-muted-foreground">{meta}</p>
            </div>
          </div>
        )}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-44">
        <ContextMenuItem onClick={onRestore}>
          <RotateCcw className="size-4" /> Restore
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" onClick={onPurge}>
          <Trash2 className="size-4" /> Delete forever
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

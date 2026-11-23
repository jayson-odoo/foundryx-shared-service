'use client';

/**
 * The drive's Trash under the Foundryx UIUX switch (slice W3-DOCS).
 *
 * The entries and their right-click menu are today's (`TrashEntry`). What
 * changes: the selection bar holds Restore and Delete forever as icon
 * actions; Delete forever asks with the playbook's typed confirm, typing the
 * one entry's name, or how many when several are ticked (owner decision),
 * instead of "DELETE"; nothing is sent before the typed text matches. A
 * restore says what came back, with Undo (it puts them back in the Trash,
 * the same request the drive's Delete sends). A delete forever cannot be
 * undone, so its toast has no Undo.
 */
import { useCallback, useEffect, useState } from 'react';
import { Folder, RotateCcw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from '@/lib/toast';
import { documentService } from '@/services/document-service';
import type { FileRow, FolderRow } from '@/types/documents';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { FxConfirmDialog } from '@/components/fx/actions/confirm-dialog';
import { fxSelectedText } from '@/components/fx/list/fx-words';
import { fileIcon, formatBytes } from './lib';
import { TrashEntry, type TrashViewProps } from './trash-view';
import { fxItems, fxPurgeExpected, fxTargetsName, useFxActorName, type DriveTargets } from './fx-drive-words';

export function FxTrashView({ view, onChanged }: TrashViewProps) {
  const byWhom = useFxActorName();
  const [folders, setFolders] = useState<FolderRow[]>([]);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selFolders, setSelFolders] = useState<Set<string>>(new Set());
  const [selFiles, setSelFiles] = useState<Set<string>>(new Set());
  const [purge, setPurge] = useState<DriveTargets | null>(null);

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

  const nameOf = (kind: 'folder' | 'file', id: string) =>
    kind === 'folder' ? folders.find((f) => f.id === id)?.name : files.find((f) => f.id === id)?.name;

  const clearSel = () => {
    setSelFolders(new Set());
    setSelFiles(new Set());
  };
  const count = selFolders.size + selFiles.size;

  const toggle = (set: React.Dispatch<React.SetStateAction<Set<string>>>) => (id: string) =>
    set((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleFolder = toggle(setSelFolders);
  const toggleFile = toggle(setSelFiles);

  const selectionTargets = (): DriveTargets => ({
    folderIds: Array.from(selFolders),
    fileIds: Array.from(selFiles),
  });

  const restore = async (targets: DriveTargets) => {
    const what = fxTargetsName(targets, nameOf);
    if (targets.folderIds.length) await documentService.restoreFolders(targets.folderIds);
    if (targets.fileIds.length) await documentService.restoreFiles(targets.fileIds);
    clearSel();
    await load();
    onChanged();
    toast.fxDone({
      what: `${what} restored`,
      byWhom,
      undo: () => {
        void (async () => {
          try {
            if (targets.folderIds.length) await documentService.deleteFolders(targets.folderIds);
            if (targets.fileIds.length) await documentService.deleteFiles(targets.fileIds);
          } catch (e) {
            toast.error(e instanceof Error && e.message ? e.message : `Couldn't put ${what} back in the Trash.`);
          }
          await load();
          onChanged();
        })();
      },
    });
  };

  const doPurge = async () => {
    if (!purge) return;
    const targets = purge;
    const what = fxTargetsName(targets, nameOf);
    setPurge(null);
    if (targets.folderIds.length) await documentService.purgeFolders(targets.folderIds);
    if (targets.fileIds.length) await documentService.purgeFiles(targets.fileIds);
    clearSel();
    await load();
    onChanged();
    toast.fxDone({ what: `${what} deleted forever`, byWhom });
  };

  const empty = folders.length === 0 && files.length === 0;
  const purgeCount = purge ? purge.folderIds.length + purge.fileIds.length : 0;
  const purgeName = purge ? fxTargetsName(purge, nameOf) : '';

  return (
    <div className="p-1">
      {count > 0 && (
        <div
          role="toolbar"
          aria-label="Selection"
          className="mb-3 flex items-center gap-2 rounded-(--fx-r-m) border border-(--fx-line) bg-(--fx-surface) px-3 py-1"
        >
          <span aria-live="polite" className="text-sm font-semibold tabular-nums text-(--fx-ink)">
            {fxSelectedText(count)}
          </span>
          <div className="ms-auto flex items-center gap-1">
            <FxIconAction
              label={`Restore ${fxItems(count)}`}
              icon={<RotateCcw className="size-[1.125rem]" aria-hidden="true" />}
              onClick={() => void restore(selectionTargets())}
            />
            <FxIconAction
              label={`Delete ${fxItems(count)} forever`}
              icon="trash"
              tone="delete"
              onClick={() => setPurge(selectionTargets())}
            />
            <FxIconAction label="Clear selection" icon="close" onClick={clearSel} />
          </div>
        </div>
      )}

      {loading ? (
        <p className="p-6 text-center text-sm text-(--fx-ink-2)">Loading the Trash</p>
      ) : empty ? (
        <div className="flex h-56 flex-col items-center justify-center gap-1 text-center">
          <p className="text-base font-semibold text-(--fx-ink)">The Trash is empty</p>
          <p className="text-sm text-(--fx-ink-2)">Files and folders you delete wait here.</p>
        </div>
      ) : (
        <div
          className={cn(
            view === 'card'
              ? 'grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5'
              : 'flex flex-col rounded-(--fx-r-m) border border-(--fx-line)',
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

      <FxConfirmDialog
        open={purge !== null}
        title={`Delete ${purgeName} forever?`}
        line={
          purgeCount === 1
            ? 'Every stored version goes too. It can’t be brought back.'
            : `All ${purgeCount} and every stored version go. They can’t be brought back.`
        }
        keepLabel="Keep in Trash"
        actionLabel={purgeCount === 1 ? 'Delete forever' : `Delete ${fxItems(purgeCount)} forever`}
        destructive
        typed={purge ? { expected: fxPurgeExpected(purge, nameOf) } : undefined}
        onKeep={() => setPurge(null)}
        onConfirm={() => void doPurge()}
      />
    </div>
  );
}

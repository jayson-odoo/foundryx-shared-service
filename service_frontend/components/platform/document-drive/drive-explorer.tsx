'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  ChevronRight,
  Download,
  Eye,
  Folder,
  FolderInput,
  FolderPlus,
  HardDrive,
  Info,
  LayoutGrid,
  List,
  Pencil,
  Share2,
  Trash2,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useCan } from '@/hooks/use-can';
import { cn } from '@/lib/utils';
import { documentService } from '@/services/document-service';
import type { FileRow, FolderRow, SharedWithMeItem } from '@/types/documents';
import { CursorMenu, type CursorMenuItem, type CursorMenuState } from './cursor-menu';
import { ShareDialog, type ShareTarget } from './share-dialog';
import { DetailsPanel, type DetailsTarget } from './details-panel';
import { DriveGrid, type DriveView, type EntryRef } from './drive-grid';
import { useDownloads } from './downloads-manager';
import { FolderTree } from './folder-tree';
import { canPreview, formatBytes } from './lib';
import { MoveDialog } from './move-dialog';
import { NameDialog } from './name-dialog';
import { PreviewDialog } from './preview-dialog';
import { SharedItemView } from './shared-item-view';
import { SharedWithMeGrid } from './shared-with-me-grid';
import { TrashView } from './trash-view';
import { UploadDialog } from './upload-dialog';
import { useDrive } from './use-drive';
import { useUploadManager } from './upload-manager';

type Section = 'drive' | 'shared' | 'trash';
interface Targets {
  folderIds: string[];
  fileIds: string[];
}
interface PendingRename {
  kind: 'folder' | 'file';
  id: string;
  name: string;
}

export function DriveExplorer() {
  const drive = useDrive();
  const uploads = useUploadManager();
  const downloads = useDownloads();
  const searchParams = useSearchParams();
  const { can } = useCan();
  const canShare = can('documents.share');

  const [sharedItems, setSharedItems] = useState<SharedWithMeItem[]>([]);
  const [sharedLoading, setSharedLoading] = useState(false);
  // The opened "Shared with me" item (browsed in place), token or null.
  const [openedShare, setOpenedShare] = useState<string | null>(null);

  const [section, setSection] = useState<Section>('drive');
  const [view, setView] = useState<DriveView>('card');
  const [treeKey, setTreeKey] = useState(0);
  const [newFolderParent, setNewFolderParent] = useState<{ parentId: string | null } | null>(null);
  const [rename, setRename] = useState<PendingRename | null>(null);
  const [moveItems, setMoveItems] = useState<Targets | null>(null);
  const [preview, setPreview] = useState<FileRow | null>(null);
  const [details, setDetails] = useState<DetailsTarget | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [menu, setMenu] = useState<CursorMenuState | null>(null);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  const openShare = (entry: EntryRef) => {
    const name =
      entry.kind === 'folder'
        ? drive.listing?.folders.find((x) => x.id === entry.id)?.name
        : drive.listing?.files.find((x) => x.id === entry.id)?.name;
    setShareTarget({ kind: entry.kind, id: entry.id, name: name ?? 'Item' });
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  useEffect(() => {
    if (uploads.completedVersion > 0) {
      void drive.reload();
      setTreeKey((k) => k + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploads.completedVersion]);

  const afterStructuralChange = async () => {
    await drive.reload();
    setTreeKey((k) => k + 1);
  };

  const onDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const target = (over.data.current?.folderId ?? null) as string | null;
    const dragged = active.data.current as EntryRef | undefined;
    if (!dragged) return;
    if (dragged.kind === 'folder' && target === dragged.id) return;

    const inSelection =
      dragged.kind === 'folder'
        ? drive.isFolderSelected(dragged.id)
        : drive.isFileSelected(dragged.id);
    const items = inSelection
      ? selectionTargets()
      : {
          folderIds: dragged.kind === 'folder' ? [dragged.id] : [],
          fileIds: dragged.kind === 'file' ? [dragged.id] : [],
        };
    try {
      await drive.moveTo(target, items);
      setTreeKey((k) => k + 1);
    } catch {
      /* cycle guard - item stays put */
    }
  };

  // ── action helpers (also used by the cursor menu) ──
  const selectionTargets = (): Targets => ({
    folderIds: Array.from(drive.selection.folderIds),
    fileIds: Array.from(drive.selection.fileIds),
  });

  const doDownload = (t: Targets) => {
    if (t.folderIds.length === 0 && t.fileIds.length === 1) {
      void downloadSingle(t.fileIds[0]);
    } else {
      void downloads.requestZip({ fileIds: t.fileIds, folderIds: t.folderIds });
    }
  };

  const doDelete = (t: Targets) =>
    void drive.deleteSelection(t).then(() => setTreeKey((k) => k + 1));

  const openDetails = (entry: EntryRef) => {
    if (entry.kind === 'folder') {
      const folder = drive.listing?.folders.find((x) => x.id === entry.id);
      if (folder) setDetails({ kind: 'folder', folder });
    } else {
      const file = drive.listing?.files.find((x) => x.id === entry.id);
      if (file) setDetails({ kind: 'file', file });
    }
  };

  const openRename = (entry: EntryRef) => {
    const name =
      entry.kind === 'folder'
        ? drive.listing?.folders.find((x) => x.id === entry.id)?.name
        : drive.listing?.files.find((x) => x.id === entry.id)?.name;
    setRename({ kind: entry.kind, id: entry.id, name: name ?? '' });
  };

  const downloadSingle = async (fileId: string) => {
    const blob = await documentService.downloadFile(fileId);
    const name = drive.listing?.files.find((x) => x.id === fileId)?.name ?? 'download';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const goDrive = (id: string | null) => {
    setSection('drive');
    setDetails(null);
    drive.navigate(id);
  };

  const openShared = (token?: string | null) => {
    drive.clearSelection();
    setDetails(null);
    setSection('shared');
    setOpenedShare(token ?? null);
    setSharedLoading(true);
    documentService
      .listSharedWithMe()
      .then(setSharedItems)
      .catch(() => setSharedItems([]))
      .finally(() => setSharedLoading(false));
  };

  // A workspace/named-people link routes here as `/documents?shared=<token>` -
  // open the Shared-with-me section with that item already browsing in place.
  useEffect(() => {
    const shared = searchParams.get('shared');
    if (shared) openShared(shared === '1' ? null : shared);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── cursor context menu ──
  const onContextMenu = (e: React.MouseEvent, entry: EntryRef) => {
    e.preventDefault();
    const inSel =
      entry.kind === 'folder'
        ? drive.isFolderSelected(entry.id)
        : drive.isFileSelected(entry.id);
    let targets: Targets;
    if (inSel) {
      targets = selectionTargets();
    } else {
      // Right-click on an unselected item selects just it (Finder behaviour).
      drive.selectOnly(entry.kind, entry.id);
      targets = {
        folderIds: entry.kind === 'folder' ? [entry.id] : [],
        fileIds: entry.kind === 'file' ? [entry.id] : [],
      };
    }
    const total = targets.folderIds.length + targets.fileIds.length;
    const items: CursorMenuItem[] = [];

    if (total === 1) {
      if (entry.kind === 'folder') {
        items.push({ id: 'open', label: 'Open', icon: Folder, onSelect: () => goDrive(entry.id) });
      } else {
        const file = drive.listing?.files.find((x) => x.id === entry.id);
        if (file && canPreview(file)) {
          items.push({ id: 'preview', label: 'Preview', icon: Eye, onSelect: () => setPreview(file) });
        }
      }
      items.push({
        id: 'download',
        label: entry.kind === 'folder' ? 'Download ZIP' : 'Download',
        icon: Download,
        onSelect: () => doDownload(targets),
      });
      items.push({ id: 'details', label: 'View details', icon: Info, onSelect: () => openDetails(entry) });
      if (canShare) {
        items.push({
          id: 'share',
          label: 'Share',
          icon: Share2,
          separatorBefore: true,
          onSelect: () => openShare(entry),
        });
      }
      items.push({
        id: 'rename',
        label: 'Rename',
        icon: Pencil,
        separatorBefore: !canShare,
        onSelect: () => openRename(entry),
      });
      items.push({ id: 'move', label: 'Move to…', icon: FolderInput, onSelect: () => setMoveItems(targets) });
      items.push({
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        danger: true,
        separatorBefore: true,
        onSelect: () => doDelete(targets),
      });
    } else {
      items.push({ id: 'download', label: `Download ZIP (${total})`, icon: Download, onSelect: () => doDownload(targets) });
      items.push({ id: 'move', label: 'Move to…', icon: FolderInput, onSelect: () => setMoveItems(targets) });
      items.push({
        id: 'delete',
        label: `Delete (${total})`,
        icon: Trash2,
        danger: true,
        separatorBefore: true,
        onSelect: () => doDelete(targets),
      });
    }
    setMenu({ x: e.clientX, y: e.clientY, items });
  };

  const usage = drive.settings;
  const usagePct =
    usage && usage.storageQuotaMb
      ? Math.min(100, (usage.usedBytes / (usage.storageQuotaMb * 1024 * 1024)) * 100)
      : 0;

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="flex flex-col gap-4 lg:flex-row">
        {/* Left: tree + storage */}
        <aside className="shrink-0 lg:w-64">
          <div className="rounded-lg border bg-card p-3 lg:sticky lg:top-4">
            <ScrollArea className="max-h-[60vh] lg:max-h-[calc(100vh-12rem)]">
              <FolderTree
                currentFolderId={drive.folderId}
                view={section}
                onNavigate={goDrive}
                onOpenShared={openShared}
                onOpenTrash={() => {
                  drive.clearSelection();
                  setDetails(null);
                  setSection('trash');
                }}
                actions={{
                  onRename: (folder: FolderRow) =>
                    setRename({ kind: 'folder', id: folder.id, name: folder.name }),
                  onDelete: (folderId: string) =>
                    doDelete({ folderIds: [folderId], fileIds: [] }),
                  onNewSubfolder: (parentId: string) => setNewFolderParent({ parentId }),
                }}
                reloadKey={treeKey}
              />
            </ScrollArea>
            {usage && (
              <div className="mt-3 border-t pt-3">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Storage</span>
                  <span>
                    {usage.storageQuotaMb
                      ? `${formatBytes(usage.usedBytes)} / ${usage.storageQuotaMb >= 1024 ? `${(usage.storageQuotaMb / 1024).toFixed(0)} GB` : `${usage.storageQuotaMb} MB`}`
                      : formatBytes(usage.usedBytes)}
                  </span>
                </div>
                {usage.storageQuotaMb != null && (
                  <Progress value={usagePct} className="mt-1.5 h-1.5" />
                )}
              </div>
            )}
          </div>
        </aside>

        {/* Main */}
        <div className="min-w-0 flex-1">
          {/* Toolbar */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div data-testid="drive-breadcrumb" className="flex items-center gap-1 overflow-x-auto text-sm">
              <button
                type="button"
                className={cn(
                  'inline-flex items-center gap-1 rounded px-1.5 py-1 hover:bg-muted',
                  section === 'drive' && drive.folderId === null && 'font-medium text-primary',
                )}
                onClick={() => goDrive(null)}
              >
                <HardDrive className="size-4" /> Drive
              </button>
              {section === 'drive' &&
                drive.listing?.breadcrumb.map((c) => (
                  <span key={c.id} className="inline-flex items-center gap-1">
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                    <button
                      type="button"
                      className="whitespace-nowrap rounded px-1.5 py-1 hover:bg-muted"
                      onClick={() => goDrive(c.id)}
                    >
                      {c.name}
                    </button>
                  </span>
                ))}
              {section === 'shared' && (
                <span className="inline-flex items-center gap-1">
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                  {openedShare ? (
                    <button
                      type="button"
                      className="whitespace-nowrap rounded px-1.5 py-1 hover:bg-muted"
                      onClick={() => setOpenedShare(null)}
                    >
                      Shared with me
                    </button>
                  ) : (
                    <span className="px-1.5 py-1 font-medium">Shared with me</span>
                  )}
                </span>
              )}
              {section === 'trash' && (
                <span className="inline-flex items-center gap-1">
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                  <span className="px-1.5 py-1 font-medium">Trash</span>
                </span>
              )}
            </div>

            <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
              <div className="flex items-center rounded-md border p-0.5">
                <button
                  type="button"
                  aria-label="Card view"
                  onClick={() => setView('card')}
                  className={cn(
                    'rounded p-1.5',
                    view === 'card' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted',
                  )}
                >
                  <LayoutGrid className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label="List view"
                  onClick={() => setView('list')}
                  className={cn(
                    'rounded p-1.5',
                    view === 'list' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted',
                  )}
                >
                  <List className="size-4" />
                </button>
              </div>
              {section === 'drive' && (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setNewFolderParent({ parentId: drive.folderId })}
                  >
                    <FolderPlus className="size-4" /> New folder
                  </Button>
                  <Button size="sm" onClick={() => setUploadOpen(true)}>
                    <Upload className="size-4" /> Upload
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* Selection indicator (actions live in the right-click menu) */}
          {section === 'drive' && drive.selectedCount > 0 && (
            <div className="mb-3 flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
              <span>{drive.selectedCount} selected</span>
              <button
                type="button"
                className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                onClick={drive.clearSelection}
              >
                Clear
              </button>
              <span className="ml-auto text-xs text-muted-foreground">
                Right-click for actions
              </span>
            </div>
          )}

          {/* Body + optional details column */}
          <div className="flex flex-col gap-4 xl:flex-row">
            <div
              className="min-h-[24rem] flex-1 rounded-lg border bg-background"
              onDragOver={(e) => section === 'drive' && e.preventDefault()}
              onDrop={(e) => {
                if (section !== 'drive') return;
                const files = Array.from(e.dataTransfer.files);
                if (files.length) {
                  e.preventDefault();
                  uploads.enqueue(files, { folderId: drive.folderId });
                }
              }}
            >
              {section === 'shared' ? (
                openedShare ? (
                  <SharedItemView token={openedShare} />
                ) : (
                  <SharedWithMeGrid
                    items={sharedItems}
                    loading={sharedLoading}
                    onOpen={(token) => setOpenedShare(token)}
                  />
                )
              ) : section === 'trash' ? (
                <TrashView view={view} onChanged={afterStructuralChange} />
              ) : drive.loading ? (
                <p className="p-10 text-center text-sm text-muted-foreground">Loading…</p>
              ) : drive.error ? (
                <p className="p-10 text-center text-sm text-destructive">{drive.error}</p>
              ) : drive.listing ? (
                <DriveGrid
                  listing={drive.listing}
                  view={view}
                  isFolderSelected={drive.isFolderSelected}
                  isFileSelected={drive.isFileSelected}
                  onToggleFolder={(id) => drive.toggleFolder(id, true)}
                  onToggleFile={(id) => drive.toggleFile(id, true)}
                  onOpenFolder={(id) => goDrive(id)}
                  onPreviewFile={setPreview}
                  onContextMenu={onContextMenu}
                  onClearSelection={drive.clearSelection}
                />
              ) : null}
            </div>

            {details && <DetailsPanel target={details} onClose={() => setDetails(null)} />}
          </div>
        </div>
      </div>

      {/* Cursor-anchored right-click menu */}
      <CursorMenu state={menu} onClose={() => setMenu(null)} />

      {/* Dialogs */}
      <UploadDialog open={uploadOpen} folderId={drive.folderId} onClose={() => setUploadOpen(false)} />
      <NameDialog
        open={newFolderParent !== null}
        title="New folder"
        label="Folder name"
        confirmLabel="Create"
        onSubmit={async (name) => {
          await drive.createFolder(name, newFolderParent?.parentId ?? null);
          setTreeKey((k) => k + 1);
        }}
        onClose={() => setNewFolderParent(null)}
      />
      <NameDialog
        open={!!rename}
        title={rename?.kind === 'folder' ? 'Rename folder' : 'Rename file'}
        label="Name"
        initialValue={rename?.name}
        onSubmit={async (name) => {
          if (!rename) return;
          if (rename.kind === 'folder') {
            await drive.renameFolder(rename.id, name);
            setTreeKey((k) => k + 1);
          } else {
            await drive.renameFile(rename.id, name);
          }
        }}
        onClose={() => setRename(null)}
      />
      <MoveDialog
        open={!!moveItems}
        movingFolderIds={moveItems?.folderIds ?? []}
        sourceFolderId={drive.folderId}
        onMove={async (target) => {
          if (moveItems) await drive.moveTo(target, moveItems);
          setTreeKey((k) => k + 1);
        }}
        onClose={() => setMoveItems(null)}
      />
      <PreviewDialog
        file={preview}
        onClose={() => setPreview(null)}
        onDownload={(id) => void downloadSingle(id)}
      />
      <ShareDialog
        target={shareTarget}
        ceiling={drive.settings?.publicSharing ?? 'off'}
        canManage={can('documents.manage')}
        onClose={() => setShareTarget(null)}
      />
    </DndContext>
  );
}

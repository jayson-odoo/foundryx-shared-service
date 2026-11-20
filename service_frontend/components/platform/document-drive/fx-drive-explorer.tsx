'use client';

/**
 * The drive under the Foundryx UIUX switch (slice W3-DOCS).
 *
 * The folder tree, the card and list grids, drag to move, the right-click
 * menu and every dialog are today's (an agreed SS difference: the explorer is
 * not a playbook list). What changes is the chrome around them:
 * - Upload is the page's red action ("Upload files to Quotations"); New
 *   folder is an icon action beside it. In Shared with me and Trash there is
 *   nothing to upload, so neither shows.
 * - Card or list view is a segmented toggle.
 * - Ticking entries opens a selection bar with their actions as icon
 *   buttons (Download, Move, Share, Rename, Move to Trash), the same
 *   handlers the right-click menu runs, instead of "Right-click for actions".
 * - Done toasts say what, and who did it. Move to Trash, Rename and Move
 *   have Undo (the same restore, rename and move requests); a new folder has
 *   none (the API can only trash it, which does not undo it).
 * Every request is today's for the same input.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
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
} from 'lucide-react';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import {
  useHideMainAction,
  useRegisterMainAction,
  useRegisterOtherActions,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { fxSelectedText } from '@/components/fx/list/fx-words';
import { useCan } from '@/hooks/use-can';
import { toast } from '@/lib/toast';
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
import { FxTrashView } from './fx-trash-view';
import { FxUploadDialog } from './fx-upload-dialog';
import { useDrive } from './use-drive';
import { useUploadManager } from './upload-manager';
import { fxItems, fxTargetsName, useFxActorName, type DriveTargets } from './fx-drive-words';

type Section = 'drive' | 'shared' | 'trash';
interface PendingRename {
  kind: 'folder' | 'file';
  id: string;
  name: string;
}

const ICON = 'size-[1.125rem]';

function failed(e: unknown, fallback: string) {
  toast.error(e instanceof Error && e.message ? e.message : fallback);
}

export function FxDriveExplorer() {
  const drive = useDrive();
  const uploads = useUploadManager();
  const downloads = useDownloads();
  const searchParams = useSearchParams();
  const { can } = useCan();
  const canShare = can('documents.share');
  const byWhom = useFxActorName();

  const [sharedItems, setSharedItems] = useState<SharedWithMeItem[]>([]);
  const [sharedLoading, setSharedLoading] = useState(false);
  const [openedShare, setOpenedShare] = useState<string | null>(null);

  const [section, setSection] = useState<Section>('drive');
  const [view, setView] = useState<DriveView>('card');
  const [treeKey, setTreeKey] = useState(0);
  const [newFolderParent, setNewFolderParent] = useState<{ parentId: string | null } | null>(null);
  const [rename, setRename] = useState<PendingRename | null>(null);
  const [moveItems, setMoveItems] = useState<DriveTargets | null>(null);
  const [preview, setPreview] = useState<FileRow | null>(null);
  const [details, setDetails] = useState<DetailsTarget | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [menu, setMenu] = useState<CursorMenuState | null>(null);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  // A dialog's own button is the one action meanwhile ("Never twice").
  useHideMainAction(
    uploadOpen || newFolderParent !== null || rename !== null || moveItems !== null || shareTarget !== null || preview !== null,
  );

  const nameOf = (kind: 'folder' | 'file', id: string) =>
    kind === 'folder'
      ? drive.listing?.folders.find((x) => x.id === id)?.name
      : drive.listing?.files.find((x) => x.id === id)?.name;

  const folderName =
    drive.folderId === null
      ? 'Drive'
      : (drive.listing?.breadcrumb.find((c) => c.id === drive.folderId)?.name ?? drive.listing?.folder?.name ?? 'this folder');

  const openShare = (entry: EntryRef) => {
    setShareTarget({ kind: entry.kind, id: entry.id, name: nameOf(entry.kind, entry.id) ?? 'Item' });
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

  const selectionTargets = (): DriveTargets => ({
    folderIds: Array.from(drive.selection.folderIds),
    fileIds: Array.from(drive.selection.fileIds),
  });

  /** Moves `items` to `target` (today's requests), then toasts with an Undo
   *  that moves them back to the folder they came from. */
  const moveWithToast = async (target: string | null, items: DriveTargets) => {
    const from = drive.folderId;
    const what = fxTargetsName(items, nameOf);
    await drive.moveTo(target, items);
    setTreeKey((k) => k + 1);
    toast.fxDone({
      what: `${what} moved`,
      byWhom,
      undo: () => {
        void (async () => {
          try {
            if (items.folderIds.length) await documentService.moveFolders(items.folderIds, { targetFolderId: from });
            if (items.fileIds.length) await documentService.moveFiles(items.fileIds, { targetFolderId: from });
          } catch (e) {
            failed(e, `Couldn't move ${what} back.`);
          }
          await afterStructuralChange();
        })();
      },
    });
  };

  const onDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const target = (over.data.current?.folderId ?? null) as string | null;
    const dragged = active.data.current as EntryRef | undefined;
    if (!dragged) return;
    if (dragged.kind === 'folder' && target === dragged.id) return;

    const inSelection =
      dragged.kind === 'folder' ? drive.isFolderSelected(dragged.id) : drive.isFileSelected(dragged.id);
    const items = inSelection
      ? selectionTargets()
      : {
          folderIds: dragged.kind === 'folder' ? [dragged.id] : [],
          fileIds: dragged.kind === 'file' ? [dragged.id] : [],
        };
    try {
      await moveWithToast(target, items);
    } catch {
      /* cycle guard - item stays put */
    }
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

  const doDownload = (t: DriveTargets) => {
    if (t.folderIds.length === 0 && t.fileIds.length === 1) {
      void downloadSingle(t.fileIds[0]);
    } else {
      void downloads.requestZip({ fileIds: t.fileIds, folderIds: t.folderIds });
    }
  };

  const doDelete = (t: DriveTargets) => {
    const what = fxTargetsName(t, nameOf);
    void drive.deleteSelection(t).then(() => {
      setTreeKey((k) => k + 1);
      toast.fxDone({
        what: `${what} moved to Trash`,
        byWhom,
        undo: () => {
          void (async () => {
            try {
              if (t.folderIds.length) await documentService.restoreFolders(t.folderIds);
              if (t.fileIds.length) await documentService.restoreFiles(t.fileIds);
            } catch (e) {
              failed(e, `Couldn't restore ${what}.`);
            }
            await afterStructuralChange();
          })();
        },
      });
    });
  };

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
    setRename({ kind: entry.kind, id: entry.id, name: nameOf(entry.kind, entry.id) ?? '' });
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

  useEffect(() => {
    const shared = searchParams.get('shared');
    if (shared) openShared(shared === '1' ? null : shared);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── page header: red action Upload, icon action New folder ──
  const openUpload = useCallback(() => setUploadOpen(true), []);
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      section === 'drive'
        ? { id: 'upload', label: 'Upload', fullLabel: `Upload files to ${folderName}`, onClick: openUpload }
        : null,
    [section, folderName, openUpload],
  );
  useRegisterMainAction(main);
  const currentFolder = drive.folderId;
  const others = useMemo<FxOtherActionSpec[]>(
    () =>
      section === 'drive'
        ? [
            {
              id: 'new-folder',
              label: 'New folder',
              icon: <FolderPlus className={ICON} aria-hidden="true" />,
              onClick: () => setNewFolderParent({ parentId: currentFolder }),
            },
          ]
        : [],
    [section, currentFolder],
  );
  useRegisterOtherActions(others);

  // ── cursor context menu (today's items and handlers) ──
  const onContextMenu = (e: React.MouseEvent, entry: EntryRef) => {
    e.preventDefault();
    const inSel = entry.kind === 'folder' ? drive.isFolderSelected(entry.id) : drive.isFileSelected(entry.id);
    let targets: DriveTargets;
    if (inSel) {
      targets = selectionTargets();
    } else {
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
        items.push({ id: 'share', label: 'Share', icon: Share2, separatorBefore: true, onSelect: () => openShare(entry) });
      }
      items.push({ id: 'rename', label: 'Rename', icon: Pencil, separatorBefore: !canShare, onSelect: () => openRename(entry) });
      items.push({ id: 'move', label: 'Move to…', icon: FolderInput, onSelect: () => setMoveItems(targets) });
      items.push({ id: 'delete', label: 'Move to Trash', icon: Trash2, danger: true, separatorBefore: true, onSelect: () => doDelete(targets) });
    } else {
      items.push({ id: 'download', label: `Download ZIP (${total})`, icon: Download, onSelect: () => doDownload(targets) });
      items.push({ id: 'move', label: 'Move to…', icon: FolderInput, onSelect: () => setMoveItems(targets) });
      items.push({
        id: 'delete',
        label: `Move ${fxItems(total)} to Trash`,
        icon: Trash2,
        danger: true,
        separatorBefore: true,
        onSelect: () => doDelete(targets),
      });
    }
    setMenu({ x: e.clientX, y: e.clientY, items });
  };

  // ── selection bar (the ticked entries' actions as icon buttons) ──
  const selected = selectionTargets();
  const selectedOne: EntryRef | null =
    drive.selectedCount === 1
      ? selected.folderIds.length
        ? { kind: 'folder', id: selected.folderIds[0] }
        : { kind: 'file', id: selected.fileIds[0] }
      : null;

  const usage = drive.settings;
  const usagePct =
    usage && usage.storageQuotaMb ? Math.min(100, (usage.usedBytes / (usage.storageQuotaMb * 1024 * 1024)) * 100) : 0;

  const crumbClass = cn(
    'inline-flex items-center gap-1 whitespace-nowrap rounded-(--fx-r-s) px-1.5 py-1 text-(--fx-ink-2) transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out) hover:bg-(--fx-surface-2) hover:text-(--fx-ink)',
  );

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="flex flex-col gap-4 lg:flex-row" data-fx-drive="">
        {/* Left: tree + storage */}
        <aside className="shrink-0 lg:w-64">
          <div className="rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-3 lg:sticky lg:top-4">
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
                  onRename: (folder: FolderRow) => setRename({ kind: 'folder', id: folder.id, name: folder.name }),
                  onDelete: (folderId: string) => doDelete({ folderIds: [folderId], fileIds: [] }),
                  onNewSubfolder: (parentId: string) => setNewFolderParent({ parentId }),
                }}
                reloadKey={treeKey}
              />
            </ScrollArea>
            {usage && (
              <div className="mt-3 border-t border-(--fx-line) pt-3">
                <div className="flex items-center justify-between text-sm text-(--fx-ink-2)">
                  <span>Storage</span>
                  <span className="tabular-nums">
                    {usage.storageQuotaMb
                      ? `${formatBytes(usage.usedBytes)} of ${usage.storageQuotaMb >= 1024 ? `${(usage.storageQuotaMb / 1024).toFixed(0)} GB` : `${usage.storageQuotaMb} MB`}`
                      : formatBytes(usage.usedBytes)}
                  </span>
                </div>
                {usage.storageQuotaMb != null && <Progress value={usagePct} className="mt-1.5 h-1.5" />}
              </div>
            )}
          </div>
        </aside>

        {/* Main */}
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <nav aria-label="Folder path" data-testid="drive-breadcrumb" className="flex min-w-0 items-center gap-1 overflow-x-auto text-sm">
              <button
                type="button"
                className={cn(PRESSED_CLASS, crumbClass, section === 'drive' && drive.folderId === null && 'font-semibold text-(--fx-ink)')}
                onClick={() => goDrive(null)}
              >
                <HardDrive className="size-4" aria-hidden="true" /> Drive
              </button>
              {section === 'drive' &&
                drive.listing?.breadcrumb.map((c, i, all) => (
                  <span key={c.id} className="inline-flex items-center gap-1">
                    <ChevronRight className="size-3.5 text-(--fx-ink-3)" aria-hidden="true" />
                    <button
                      type="button"
                      aria-current={i === all.length - 1 ? 'page' : undefined}
                      className={cn(PRESSED_CLASS, crumbClass, i === all.length - 1 && 'font-semibold text-(--fx-ink)')}
                      onClick={() => goDrive(c.id)}
                    >
                      {c.name}
                    </button>
                  </span>
                ))}
              {section === 'shared' && (
                <span className="inline-flex items-center gap-1">
                  <ChevronRight className="size-3.5 text-(--fx-ink-3)" aria-hidden="true" />
                  {openedShare ? (
                    <button type="button" className={cn(PRESSED_CLASS, crumbClass)} onClick={() => setOpenedShare(null)}>
                      Shared with me
                    </button>
                  ) : (
                    <span className="px-1.5 py-1 font-semibold text-(--fx-ink)">Shared with me</span>
                  )}
                </span>
              )}
              {section === 'trash' && (
                <span className="inline-flex items-center gap-1">
                  <ChevronRight className="size-3.5 text-(--fx-ink-3)" aria-hidden="true" />
                  <span className="px-1.5 py-1 font-semibold text-(--fx-ink)">Trash</span>
                </span>
              )}
            </nav>

            <ToggleGroup
              type="single"
              value={view}
              onValueChange={(v) => v && setView(v as DriveView)}
              aria-label="View"
              className="ms-auto"
            >
              <ToggleGroupItem value="card" aria-label="Card view">
                <LayoutGrid className="size-4" aria-hidden="true" />
              </ToggleGroupItem>
              <ToggleGroupItem value="list" aria-label="List view">
                <List className="size-4" aria-hidden="true" />
              </ToggleGroupItem>
            </ToggleGroup>
          </div>

          {section === 'drive' && drive.selectedCount > 0 && (
            <div
              role="toolbar"
              aria-label="Selection"
              className="mb-3 flex flex-wrap items-center gap-2 rounded-(--fx-r-m) border border-(--fx-line) bg-(--fx-surface) px-3 py-1"
            >
              <span aria-live="polite" className="text-sm font-semibold tabular-nums text-(--fx-ink)">
                {fxSelectedText(drive.selectedCount)}
              </span>
              <div className="ms-auto flex flex-wrap items-center justify-end gap-1">
                <FxIconAction
                  label={
                    selected.folderIds.length === 0 && selected.fileIds.length === 1
                      ? 'Download'
                      : `Download ZIP (${drive.selectedCount})`
                  }
                  icon={<Download className={ICON} aria-hidden="true" />}
                  onClick={() => doDownload(selected)}
                />
                <FxIconAction label="Move to…" icon="move" onClick={() => setMoveItems(selected)} />
                {selectedOne && canShare && (
                  <FxIconAction label="Share" icon="share" onClick={() => openShare(selectedOne)} />
                )}
                {selectedOne && <FxIconAction label="Rename" icon="edit" onClick={() => openRename(selectedOne)} />}
                <FxIconAction
                  label={drive.selectedCount === 1 ? 'Move to Trash' : `Move ${fxItems(drive.selectedCount)} to Trash`}
                  icon="trash"
                  tone="delete"
                  onClick={() => doDelete(selected)}
                />
                <FxIconAction label="Clear selection" icon="close" onClick={drive.clearSelection} />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-4 xl:flex-row">
            <div
              role="group"
              aria-label="Folder contents"
              className="min-h-[24rem] flex-1 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface)"
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
                  <SharedWithMeGrid items={sharedItems} loading={sharedLoading} onOpen={(token) => setOpenedShare(token)} />
                )
              ) : section === 'trash' ? (
                <FxTrashView view={view} onChanged={afterStructuralChange} />
              ) : drive.loading ? (
                <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-4">
                  {Array.from({ length: 8 }).map((_, index) => (
                    <Skeleton key={index} className="h-24 w-full" />
                  ))}
                </div>
              ) : drive.error ? (
                <div role="alert" className="flex flex-col items-center gap-1 p-10 text-center">
                  <p className="text-base font-semibold text-(--fx-ink)">Couldn&apos;t load this folder</p>
                  <button
                    type="button"
                    className={cn(PRESSED_CLASS, 'text-sm font-semibold text-(--fx-link) hover:underline')}
                    onClick={() => void drive.reload()}
                  >
                    Try again
                  </button>
                </div>
              ) : drive.listing ? (
                drive.listing.folders.length === 0 && drive.listing.files.length === 0 ? (
                  <div className="flex h-72 flex-col items-center justify-center gap-1 text-center">
                    <p className="text-base font-semibold text-(--fx-ink)">{folderName} is empty</p>
                    <p className="text-sm text-(--fx-ink-2)">Uploaded files and new folders show here.</p>
                  </div>
                ) : (
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
                )
              ) : null}
            </div>

            {details && <DetailsPanel target={details} onClose={() => setDetails(null)} />}
          </div>
        </div>
      </div>

      <CursorMenu state={menu} onClose={() => setMenu(null)} />

      <FxUploadDialog open={uploadOpen} folderId={drive.folderId} folderName={folderName} onClose={() => setUploadOpen(false)} />
      <NameDialog
        open={newFolderParent !== null}
        title="New folder"
        label="Folder name"
        confirmLabel="Create folder"
        onSubmit={async (name) => {
          await drive.createFolder(name, newFolderParent?.parentId ?? null);
          setTreeKey((k) => k + 1);
          toast.fxDone({ what: `Folder ${name} created`, byWhom });
        }}
        onClose={() => setNewFolderParent(null)}
      />
      <NameDialog
        open={!!rename}
        title={rename?.kind === 'folder' ? 'Rename folder' : 'Rename file'}
        label="Name"
        confirmLabel={rename?.kind === 'folder' ? 'Rename folder' : 'Rename file'}
        initialValue={rename?.name}
        onSubmit={async (name) => {
          if (!rename) return;
          const before = rename;
          if (before.kind === 'folder') {
            await drive.renameFolder(before.id, name);
            setTreeKey((k) => k + 1);
          } else {
            await drive.renameFile(before.id, name);
          }
          if (before.name && before.name !== name) {
            toast.fxDone({
              what: `${before.name} renamed to ${name}`,
              byWhom,
              undo: () => {
                void (async () => {
                  try {
                    if (before.kind === 'folder') {
                      await drive.renameFolder(before.id, before.name);
                      setTreeKey((k) => k + 1);
                    } else {
                      await drive.renameFile(before.id, before.name);
                    }
                  } catch (e) {
                    failed(e, `Couldn't rename ${name} back.`);
                  }
                })();
              },
            });
          }
        }}
        onClose={() => setRename(null)}
      />
      <MoveDialog
        open={!!moveItems}
        movingFolderIds={moveItems?.folderIds ?? []}
        sourceFolderId={drive.folderId}
        onMove={async (target) => {
          if (moveItems) await moveWithToast(target, moveItems);
          setTreeKey((k) => k + 1);
        }}
        onClose={() => setMoveItems(null)}
      />
      <PreviewDialog file={preview} onClose={() => setPreview(null)} onDownload={(id) => void downloadSingle(id)} />
      <ShareDialog
        target={shareTarget}
        ceiling={drive.settings?.publicSharing ?? 'off'}
        canManage={can('documents.manage')}
        onClose={() => setShareTarget(null)}
      />
    </DndContext>
  );
}

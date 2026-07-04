'use client';

import { useDraggable, useDroppable } from '@dnd-kit/core';
import { Folder } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { useDatetime } from '@/hooks/use-datetime';
import { cn } from '@/lib/utils';
import type { FileRow, FolderListing, FolderRow } from '@/types/documents';
import { fileIcon, formatBytes } from './lib';

export type DriveView = 'card' | 'list';

export type EntryAction =
  | 'open'
  | 'preview'
  | 'select'
  | 'download'
  | 'details'
  | 'rename'
  | 'move'
  | 'delete';

export type EntryRef = { kind: 'folder' | 'file'; id: string };

export interface DriveGridProps {
  listing: FolderListing;
  view: DriveView;
  isFolderSelected: (id: string) => boolean;
  isFileSelected: (id: string) => boolean;
  onToggleFolder: (id: string) => void;
  onToggleFile: (id: string) => void;
  onOpenFolder: (id: string) => void;
  onPreviewFile: (file: FileRow) => void;
  /** Right-click → the explorer opens the cursor-anchored menu. */
  onContextMenu: (e: React.MouseEvent, entry: EntryRef) => void;
  onClearSelection: () => void;
}

export function DriveGrid({
  listing,
  view,
  isFolderSelected,
  isFileSelected,
  onToggleFolder,
  onToggleFile,
  onOpenFolder,
  onPreviewFile,
  onContextMenu,
  onClearSelection,
}: DriveGridProps) {
  const empty = listing.folders.length === 0 && listing.files.length === 0;

  if (empty) {
    return (
      <div
        className="min-h-full p-1"
        onClick={(e) => e.target === e.currentTarget && onClearSelection()}
      >
        <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-muted-foreground">
          <Folder className="size-10 opacity-40" />
          <p className="text-sm">This folder is empty.</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-full p-1"
      onClick={(e) => e.target === e.currentTarget && onClearSelection()}
    >
      {view === 'list' && (
        <div className="hidden grid-cols-[auto_1fr_8rem_6rem_9rem] gap-3 border-b px-3 py-2 text-xs font-medium text-muted-foreground sm:grid">
          <span className="w-5" />
          <span>Name</span>
          <span>Type</span>
          <span>Size</span>
          <span>Modified</span>
        </div>
      )}
      <div
        className={cn(
          view === 'card'
            ? 'grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5'
            : 'flex flex-col',
        )}
      >
        {listing.folders.map((folder) => (
          <FolderEntry
            key={folder.id}
            folder={folder}
            view={view}
            selected={isFolderSelected(folder.id)}
            onToggle={onToggleFolder}
            onOpen={onOpenFolder}
            onContextMenu={onContextMenu}
          />
        ))}
        {listing.files.map((file) => (
          <FileEntry
            key={file.id}
            file={file}
            view={view}
            selected={isFileSelected(file.id)}
            onToggle={onToggleFile}
            onPreview={onPreviewFile}
            onContextMenu={onContextMenu}
          />
        ))}
      </div>
    </div>
  );
}

function FolderEntry({
  folder,
  view,
  selected,
  onToggle,
  onOpen,
  onContextMenu,
}: {
  folder: FolderRow;
  view: DriveView;
  selected: boolean;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  onContextMenu: (e: React.MouseEvent, entry: EntryRef) => void;
}) {
  const drag = useDraggable({ id: `folder:${folder.id}`, data: { kind: 'folder', id: folder.id } });
  const drop = useDroppable({ id: `drop:${folder.id}`, data: { folderId: folder.id } });
  const setRef = (node: HTMLElement | null) => {
    drag.setNodeRef(node);
    drop.setNodeRef(node);
  };
  const itemCount = folder.folderCount + folder.fileCount;

  return (
    <Shell
      kind="folder"
      name={folder.name}
      view={view}
      selected={selected}
      isOver={drop.isOver}
      icon={<Folder className="size-8 text-primary" />}
      listIcon={<Folder className="size-5 text-primary" />}
      typeLabel="Folder"
      sizeLabel="—"
      modified={folder.updatedAt}
      meta={`${itemCount} item${itemCount === 1 ? '' : 's'}`}
      setRef={setRef}
      dragProps={{ ...drag.attributes, ...drag.listeners }}
      onPrimary={() => onOpen(folder.id)}
      onToggle={() => onToggle(folder.id)}
      onContextMenu={(e) => onContextMenu(e, { kind: 'folder', id: folder.id })}
    />
  );
}

function FileEntry({
  file,
  view,
  selected,
  onToggle,
  onPreview,
  onContextMenu,
}: {
  file: FileRow;
  view: DriveView;
  selected: boolean;
  onToggle: (id: string) => void;
  onPreview: (file: FileRow) => void;
  onContextMenu: (e: React.MouseEvent, entry: EntryRef) => void;
}) {
  const drag = useDraggable({ id: `file:${file.id}`, data: { kind: 'file', id: file.id } });
  const Icon = fileIcon(file.name);
  const ext = file.name.includes('.') ? file.name.split('.').pop()!.toUpperCase() : 'File';

  return (
    <Shell
      kind="file"
      name={file.name}
      view={view}
      selected={selected}
      icon={<Icon className="size-8 text-muted-foreground" />}
      listIcon={<Icon className="size-5 text-muted-foreground" />}
      typeLabel={ext}
      sizeLabel={formatBytes(file.currentVersion.sizeBytes)}
      modified={file.updatedAt}
      meta={`${formatBytes(file.currentVersion.sizeBytes)}${file.versionCount > 1 ? ` · v${file.versionCount}` : ''}`}
      setRef={drag.setNodeRef}
      dragProps={{ ...drag.attributes, ...drag.listeners }}
      onPrimary={() => onPreview(file)}
      onToggle={() => onToggle(file.id)}
      onContextMenu={(e) => onContextMenu(e, { kind: 'file', id: file.id })}
    />
  );
}

function Shell({
  kind,
  name,
  view,
  selected,
  isOver,
  icon,
  listIcon,
  typeLabel,
  sizeLabel,
  modified,
  meta,
  setRef,
  dragProps,
  onPrimary,
  onToggle,
  onContextMenu,
}: {
  kind: 'folder' | 'file';
  name: string;
  view: DriveView;
  selected: boolean;
  isOver?: boolean;
  icon: React.ReactNode;
  listIcon: React.ReactNode;
  typeLabel: string;
  sizeLabel: string;
  modified: string;
  meta: string;
  setRef: (node: HTMLElement | null) => void;
  dragProps: Record<string, unknown>;
  onPrimary: () => void;
  onToggle: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const { formatDate } = useDatetime();
  const stopToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle();
  };

  if (view === 'list') {
    return (
      <div
        ref={setRef}
        {...dragProps}
        data-entry={kind}
        data-name={name}
        onClick={onPrimary}
        onContextMenu={onContextMenu}
        className={cn(
          'grid cursor-pointer grid-cols-[auto_1fr_8rem_6rem_9rem] items-center gap-3 rounded-md border-b px-3 py-2.5 text-sm transition last:border-b-0',
          selected ? 'bg-primary/10' : 'hover:bg-muted/60',
          isOver && 'ring-2 ring-primary',
        )}
      >
        <span onClick={stopToggle} className="flex w-5 items-center">
          <Checkbox checked={selected} aria-label={`Select ${name}`} />
        </span>
        <span className="flex min-w-0 items-center gap-2">
          {listIcon}
          <span className="truncate font-medium" title={name}>
            {name}
          </span>
        </span>
        <span className="hidden truncate text-muted-foreground sm:block">{typeLabel}</span>
        <span className="hidden text-muted-foreground sm:block">{sizeLabel}</span>
        <span className="hidden text-muted-foreground sm:block">{formatDate(modified)}</span>
      </div>
    );
  }

  return (
    <div
      ref={setRef}
      {...dragProps}
      data-entry={kind}
      data-name={name}
      onClick={onPrimary}
      onContextMenu={onContextMenu}
      className={cn(
        'group relative flex cursor-pointer flex-col gap-2 rounded-lg border bg-card p-3 transition',
        selected ? 'border-primary ring-1 ring-primary' : 'hover:border-primary/40',
        isOver && 'border-primary bg-primary/5 ring-2 ring-primary',
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
  );
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import {
  ChevronRight,
  Folder,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Pencil,
  Trash2,
  Users,
} from 'lucide-react';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { documentService } from '@/services/document-service';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Skeleton } from '@/components/ui/skeleton';
import type { FolderRow } from '@/types/documents';

/** Folder-level actions surfaced by right-clicking a tree node (sprint-3/04b). */
export interface TreeNodeActions {
  onRename: (folder: FolderRow) => void;
  onDelete: (folderId: string) => void;
  onNewSubfolder: (parentId: string) => void;
}

export interface FolderTreeProps {
  currentFolderId: string | null;
  /** 'shared'/'trash' when those views are active (Drive root un-highlighted). */
  view: 'drive' | 'shared' | 'trash';
  onNavigate: (folderId: string | null) => void;
  onOpenShared: () => void;
  onOpenTrash: () => void;
  actions: TreeNodeActions;
  /** Bump to force the whole tree to refetch after a structural change. */
  reloadKey: number;
}

/** Left sidebar: the tenant Drive tree (lazy-expand, drop targets, context
 * menu) + a Trash entry at the bottom. */
export function FolderTree({
  currentFolderId,
  view,
  onNavigate,
  onOpenShared,
  onOpenTrash,
  actions,
  reloadKey,
}: FolderTreeProps) {
  const root = useDroppable({ id: 'drop:root', data: { folderId: null } });

  return (
    <nav className="space-y-0.5 text-sm">
      <button
        type="button"
        ref={root.setNodeRef}
        onClick={() => onNavigate(null)}
        className={cn(
          PRESSED_CLASS,
          'flex w-full items-center gap-2 rounded-md px-2 py-1.5 font-medium',
          view === 'drive' && currentFolderId === null
            ? 'bg-primary/10 text-primary'
            : 'hover:bg-muted',
          root.isOver && 'ring-2 ring-primary',
        )}
      >
        <HardDrive className="size-4" /> Drive
      </button>
      <TreeLevel
        parentId={null}
        depth={0}
        currentFolderId={view === 'drive' ? currentFolderId : '__none__'}
        onNavigate={onNavigate}
        actions={actions}
        reloadKey={reloadKey}
      />
      <div className="mt-1 border-t pt-1">
        <button
          type="button"
          data-tree-shared
          onClick={onOpenShared}
          className={cn(
            PRESSED_CLASS,
            'flex w-full items-center gap-2 rounded-md px-2 py-1.5 font-medium',
            view === 'shared' ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
          )}
        >
          <Users className="size-4" /> Shared with me
        </button>
        <button
          type="button"
          data-tree-trash
          onClick={onOpenTrash}
          className={cn(
            PRESSED_CLASS,
            'flex w-full items-center gap-2 rounded-md px-2 py-1.5',
            view === 'trash' ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
          )}
        >
          <Trash2 className="size-4" /> Trash
        </button>
      </div>
    </nav>
  );
}

function TreeLevel({
  parentId,
  depth,
  currentFolderId,
  onNavigate,
  actions,
  reloadKey,
}: {
  parentId: string | null;
  depth: number;
  currentFolderId: string | null;
  onNavigate: (id: string | null) => void;
  actions: TreeNodeActions;
  reloadKey: number;
}) {
  const [folders, setFolders] = useState<FolderRow[] | null>(null);

  const load = useCallback(async () => {
    const listing = await documentService.listFolder(parentId);
    setFolders(listing.folders);
  }, [parentId]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (folders === null) {
    return depth === 0 ? (
      <div className="space-y-1 px-2 py-1">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    ) : null;
  }

  return (
    <div className={depth === 0 ? '' : 'ml-3 border-l pl-1'}>
      {folders.map((f) => (
        <TreeNode
          key={f.id}
          folder={f}
          depth={depth}
          currentFolderId={currentFolderId}
          onNavigate={onNavigate}
          actions={actions}
          reloadKey={reloadKey}
        />
      ))}
    </div>
  );
}

function TreeNode({
  folder,
  depth,
  currentFolderId,
  onNavigate,
  actions,
  reloadKey,
}: {
  folder: FolderRow;
  depth: number;
  currentFolderId: string | null;
  onNavigate: (id: string | null) => void;
  actions: TreeNodeActions;
  reloadKey: number;
}) {
  const [open, setOpen] = useState(false);
  const drop = useDroppable({ id: `drop:${folder.id}`, data: { folderId: folder.id } });
  const active = currentFolderId === folder.id;
  const hasChildren = folder.folderCount > 0;

  return (
    <div>
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div
            ref={drop.setNodeRef}
            className={cn(
              'flex items-center gap-1 rounded-md pr-1',
              active ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
              drop.isOver && 'ring-2 ring-primary',
            )}
          >
            <button
              type="button"
              aria-label={open ? 'Collapse' : 'Expand'}
              onClick={() => setOpen((v) => !v)}
              className={cn(
                PRESSED_CLASS,
                'flex size-5 shrink-0 items-center justify-center rounded',
                !hasChildren && 'invisible',
              )}
            >
              <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
            </button>
            <button
              type="button"
              data-tree-folder={folder.name}
              onClick={() => onNavigate(folder.id)}
              className={cn(PRESSED_CLASS, 'flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left')}
            >
              {active || open ? (
                <FolderOpen className="size-4 shrink-0 text-primary" />
              ) : (
                <Folder className="size-4 shrink-0 text-primary" />
              )}
              <span className="truncate">{folder.name}</span>
            </button>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-44">
          <ContextMenuItem onClick={() => actions.onNewSubfolder(folder.id)}>
            <FolderPlus className="size-4" /> New subfolder
          </ContextMenuItem>
          <ContextMenuItem onClick={() => actions.onRename(folder)}>
            <Pencil className="size-4" /> Rename
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem variant="destructive" onClick={() => actions.onDelete(folder.id)}>
            <Trash2 className="size-4" /> Delete
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      {open && (
        <TreeLevel
          parentId={folder.id}
          depth={depth + 1}
          currentFolderId={currentFolderId}
          onNavigate={onNavigate}
          actions={actions}
          reloadKey={reloadKey}
        />
      )}
    </div>
  );
}

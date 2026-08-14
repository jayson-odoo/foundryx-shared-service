'use client';

import { useCallback, useEffect, useState } from 'react';
import { documentService } from '@/services/document-service';
import type { DocumentSettings, FolderListing } from '@/types/documents';

/** Selected entries in the grid, split by kind (move/delete operate on both). */
export interface DriveSelection {
  folderIds: Set<string>;
  fileIds: Set<string>;
}

const emptySelection = (): DriveSelection => ({
  folderIds: new Set(),
  fileIds: new Set(),
});

export interface UseDrive {
  folderId: string | null;
  listing: FolderListing | null;
  settings: DocumentSettings | null;
  loading: boolean;
  error: string | null;
  selection: DriveSelection;
  selectedCount: number;
  navigate: (folderId: string | null) => void;
  reload: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  // selection
  toggleFolder: (id: string, additive: boolean) => void;
  toggleFile: (id: string, additive: boolean) => void;
  selectOnly: (kind: 'folder' | 'file', id: string) => void;
  clearSelection: () => void;
  isFolderSelected: (id: string) => boolean;
  isFileSelected: (id: string) => boolean;
  // mutations
  createFolder: (name: string, parentId?: string | null) => Promise<void>;
  renameFolder: (id: string, name: string) => Promise<void>;
  renameFile: (id: string, name: string) => Promise<void>;
  moveTo: (
    targetFolderId: string | null,
    items?: { folderIds: string[]; fileIds: string[] },
  ) => Promise<void>;
  deleteSelection: (items?: { folderIds: string[]; fileIds: string[] }) => Promise<void>;
}

/** Drive state: current folder listing, selection, and the mutating ops. */
export function useDrive(): UseDrive {
  const [folderId, setFolderId] = useState<string | null>(null);
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [settings, setSettings] = useState<DocumentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<DriveSelection>(emptySelection);

  const load = useCallback(async (id: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const result = await documentService.listFolder(id);
      setListing(result);
    } catch {
      setError('Could not load this folder.');
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      setSettings(await documentService.getSettings());
    } catch {
      /* usage bar is non-critical */
    }
  }, []);

  useEffect(() => {
    void load(folderId);
  }, [folderId, load]);

  useEffect(() => {
    void refreshSettings();
  }, [refreshSettings]);

  const reload = useCallback(async () => {
    await Promise.all([load(folderId), refreshSettings()]);
  }, [load, folderId, refreshSettings]);

  const navigate = useCallback((id: string | null) => {
    setSelection(emptySelection());
    setFolderId(id);
  }, []);

  // ── selection ──
  const toggleFolder = useCallback((id: string, additive: boolean) => {
    setSelection((prev) => {
      const folderIds = new Set(additive ? prev.folderIds : []);
      const fileIds = new Set(additive ? prev.fileIds : []);
      if (folderIds.has(id)) folderIds.delete(id);
      else folderIds.add(id);
      return { folderIds, fileIds };
    });
  }, []);

  const toggleFile = useCallback((id: string, additive: boolean) => {
    setSelection((prev) => {
      const folderIds = new Set(additive ? prev.folderIds : []);
      const fileIds = new Set(additive ? prev.fileIds : []);
      if (fileIds.has(id)) fileIds.delete(id);
      else fileIds.add(id);
      return { folderIds, fileIds };
    });
  }, []);

  const selectOnly = useCallback((kind: 'folder' | 'file', id: string) => {
    setSelection({
      folderIds: new Set(kind === 'folder' ? [id] : []),
      fileIds: new Set(kind === 'file' ? [id] : []),
    });
  }, []);

  const clearSelection = useCallback(() => setSelection(emptySelection()), []);

  // ── mutations ──
  const createFolder = useCallback(
    async (name: string, parentId?: string | null) => {
      // Default to the current folder; the tree's "New subfolder" passes an
      // explicit parent.
      await documentService.createFolder({
        parentId: parentId === undefined ? folderId : parentId,
        name,
      });
      await load(folderId);
    },
    [folderId, load],
  );

  const renameFolder = useCallback(
    async (id: string, name: string) => {
      await documentService.renameFolder(id, { name });
      await load(folderId);
    },
    [folderId, load],
  );

  const renameFile = useCallback(
    async (id: string, name: string) => {
      await documentService.renameFile(id, { name });
      await load(folderId);
    },
    [folderId, load],
  );

  const moveTo = useCallback(
    async (
      targetFolderId: string | null,
      items?: { folderIds: string[]; fileIds: string[] },
    ) => {
      const folderIds = items?.folderIds ?? Array.from(selection.folderIds);
      const fileIds = items?.fileIds ?? Array.from(selection.fileIds);
      if (folderIds.length) await documentService.moveFolders(folderIds, { targetFolderId });
      if (fileIds.length) await documentService.moveFiles(fileIds, { targetFolderId });
      setSelection(emptySelection());
      await load(folderId);
    },
    [selection, folderId, load],
  );

  const deleteSelection = useCallback(
    async (items?: { folderIds: string[]; fileIds: string[] }) => {
      // Accept explicit ids (mirrors moveTo) - a context-menu Delete must NOT
      // route through selectOnly()→deleteSelection(), which reads a stale
      // `selection` closure (the setState hasn't applied yet) and deletes
      // nothing on an unselected item.
      const folderIds = items?.folderIds ?? Array.from(selection.folderIds);
      const fileIds = items?.fileIds ?? Array.from(selection.fileIds);
      if (folderIds.length) await documentService.deleteFolders(folderIds);
      if (fileIds.length) await documentService.deleteFiles(fileIds);
      setSelection(emptySelection());
      await reload();
    },
    [selection, reload],
  );

  return {
    folderId,
    listing,
    settings,
    loading,
    error,
    selection,
    selectedCount: selection.folderIds.size + selection.fileIds.size,
    navigate,
    reload,
    refreshSettings,
    toggleFolder,
    toggleFile,
    selectOnly,
    clearSelection,
    isFolderSelected: (id) => selection.folderIds.has(id),
    isFileSelected: (id) => selection.fileIds.has(id),
    createFolder,
    renameFolder,
    renameFile,
    moveTo,
    deleteSelection,
  };
}

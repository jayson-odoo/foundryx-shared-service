import { describe, expect, it } from 'vitest';
import { mockDocumentService as svc } from './document-service.mock';
import { StorageQuotaError, UploadConflictError, UploadRejectedError } from './document-service';

/** A File of an exact byte size (jsdom File). */
function fileOf(name: string, bytes: number): File {
  return new File([new Uint8Array(bytes)], name, { type: 'application/octet-stream' });
}

async function findFolderId(parentId: string | null, name: string): Promise<string> {
  const listing = await svc.listFolder(parentId);
  const f = listing.folders.find((x) => x.name === name);
  if (!f) throw new Error(`folder ${name} not found`);
  return f.id;
}

describe('document-service mock - Drive', () => {
  it('seeds a navigable root with folders and files', async () => {
    const root = await svc.listFolder(null);
    expect(root.folders.map((f) => f.name)).toContain('Quotations');
    expect(root.files.length).toBeGreaterThan(0);
    expect(root.breadcrumb).toEqual([]);
  });

  it('navigates into a folder and resolves its breadcrumb', async () => {
    const eventsId = await findFolderId(null, 'Events');
    const listing = await svc.listFolder(eventsId);
    expect(listing.folder?.name).toBe('Events');
    expect(listing.folders.map((f) => f.name)).toContain('2026');
  });

  it('creates a folder under the current parent', async () => {
    const created = await svc.createFolder({ parentId: null, name: 'Reports' });
    expect(created.name).toBe('Reports');
    const root = await svc.listFolder(null);
    expect(root.folders.some((f) => f.id === created.id)).toBe(true);
  });

  it('renames a file without changing its id', async () => {
    const folderId = await findFolderId(null, 'Quotations');
    const listing = await svc.listFolder(folderId);
    const file = listing.files[0];
    const renamed = await svc.renameFile(file.id, { name: 'Renamed.pdf' });
    expect(renamed.id).toBe(file.id);
    expect(renamed.name).toBe('Renamed.pdf');
  });
});

describe('document-service mock - uploads', () => {
  it('uploads a new file with one version + progress', async () => {
    const target = await findFolderId(null, 'Contracts');
    const progress: number[] = [];
    const { file } = await svc.upload(fileOf('NDA.pdf', 1234), { folderId: target }, (p) =>
      progress.push(p),
    );
    expect(file.name).toBe('NDA.pdf');
    expect(file.versionCount).toBe(1);
    expect(progress.at(-1)).toBe(100);
  });

  it('rejects a blocked file type via the sniff floor', async () => {
    await expect(
      svc.upload(fileOf('malware.exe', 10), { folderId: null }),
    ).rejects.toBeInstanceOf(UploadRejectedError);
  });

  it('raises a conflict on a same-name upload, then resolves it two ways', async () => {
    const target = await findFolderId(null, 'Invoices');
    await svc.upload(fileOf('dup.pdf', 100), { folderId: target });

    // No conflict mode → 409.
    await expect(
      svc.upload(fileOf('dup.pdf', 100), { folderId: target }),
    ).rejects.toBeInstanceOf(UploadConflictError);

    // Replace → new version on the existing file.
    const replaced = await svc.upload(fileOf('dup.pdf', 200), {
      folderId: target,
      conflict: 'replace',
    });
    expect(replaced.file.versionCount).toBe(2);

    // Keep both → auto-renamed copy.
    const kept = await svc.upload(fileOf('dup.pdf', 100), {
      folderId: target,
      conflict: 'keep_both',
    });
    expect(kept.file.name).toBe('dup (1).pdf');
  });

  it('blocks an upload that would exceed the storage quota', async () => {
    await svc.updateSettings({ storageQuotaMb: 1 }); // 1 MB
    await expect(
      svc.upload(fileOf('huge.pdf', 5 * 1024 * 1024), { folderId: null }),
    ).rejects.toBeInstanceOf(StorageQuotaError);
    await svc.updateSettings({ storageQuotaMb: 4096 }); // restore headroom
  });
});

describe('document-service mock - move / trash', () => {
  it('refuses to move a folder into its own subtree (cycle guard)', async () => {
    const eventsId = await findFolderId(null, 'Events');
    const childId = await findFolderId(eventsId, '2026');
    await expect(
      svc.moveFolders([eventsId], { targetFolderId: childId }),
    ).rejects.toThrow();
  });

  it('soft-deletes a folder subtree, then restores it', async () => {
    const folder = await svc.createFolder({ parentId: null, name: 'TempDelete' });
    const child = await svc.createFolder({ parentId: folder.id, name: 'Inner' });
    await svc.upload(fileOf('inside.pdf', 50), { folderId: child.id });

    await svc.deleteFolders([folder.id]);
    const rootAfter = await svc.listFolder(null);
    expect(rootAfter.folders.some((f) => f.id === folder.id)).toBe(false);

    const trash = await svc.listTrash();
    expect(trash.folders.some((f) => f.id === folder.id)).toBe(true);
    // The child folder cascaded into trash too.
    expect(trash.folders.some((f) => f.id === child.id)).toBe(true);

    await svc.restoreFolders([folder.id]);
    const rootRestored = await svc.listFolder(null);
    expect(rootRestored.folders.some((f) => f.id === folder.id)).toBe(true);
  });
});

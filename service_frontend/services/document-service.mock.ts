/**
 * In-memory mock of the document service (Phase A - frontend-first, no backend).
 * Seeds a small tenant Drive so every state is exercisable: nested folders,
 * versioned files, an image + a PDF (inline preview), an attachment type, a
 * storage quota with live usage, a couple of download jobs.
 *
 * Behaviors faithfully simulated: name-collision 409 (Replace / Keep both),
 * quota 413, the sniff hard-floor (block exe/html/svg), folder-move cycle
 * guard, soft-delete + Trash subtree cascade, restore/purge, async ZIP jobs.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  AttachmentTypeRow,
  CreateFolderPayload,
  DocumentSettings,
  DownloadJob,
  FileRow,
  FileVersionRow,
  FolderListing,
  FolderRow,
  MovePayload,
  PreviewKind,
  RenamePayload,
  ShareRow,
  ShareUser,
  UploadOptions,
  UploadResult,
  ZipRequest,
} from '@/types/documents';
import type { DocumentService, UploadProgress } from './document-service';
import {
  StorageQuotaError,
  UploadConflictError,
  UploadRejectedError,
} from './document-service';

const MB = 1024 * 1024;
const delay = <T>(value: T, ms = 220): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms));
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

const shares: ShareRow[] = [];

// Stable-ish id generator (mock only - no Math.random reproducibility concern).
let seq = 1000;
const nid = (prefix: string) => `${prefix}_${(seq += 1)}`;

const NOW = '2026-06-12T09:00:00Z';
const DEMO_USER = 'usr_demo';
const DEMO_NAME = 'Demo Admin';

/** Magic-byte hard floor (mock = by extension): always blocked, no override. */
const BLOCKED_EXTS = new Set(['exe', 'bat', 'cmd', 'sh', 'html', 'htm', 'svg', 'js']);
const extOf = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';

const PREVIEW_BY_EXT: Record<string, PreviewKind> = {
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  webp: 'image',
  gif: 'image',
  pdf: 'pdf',
};
const previewKindOf = (name: string): PreviewKind =>
  PREVIEW_BY_EXT[extOf(name)] ?? 'none';

const mimeByExt: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv',
  txt: 'text/plain',
  zip: 'application/zip',
};
const mimeOf = (name: string) => mimeByExt[extOf(name)] ?? 'application/octet-stream';

// ── Internal store records ──────────────────────────────────────────────────

interface FolderRec {
  id: string;
  parentId: string | null;
  name: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  deleted: boolean;
}
interface VersionRec {
  id: string;
  ordinal: number;
  sizeBytes: number;
  mime: string;
  uploadedBy: string;
  createdAt: string;
}
interface FileRec {
  id: string;
  folderId: string | null;
  name: string;
  typeId: string | null;
  versions: VersionRec[];
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  deleted: boolean;
}

// ── Seed ────────────────────────────────────────────────────────────────────

const folders: FolderRec[] = [
  fld('fld_quotations', null, 'Quotations'),
  fld('fld_invoices', null, 'Invoices'),
  fld('fld_events', null, 'Events'),
  fld('fld_events_2026', 'fld_events', '2026'),
  fld('fld_contracts', null, 'Contracts'),
];

const files: FileRec[] = [
  file('Acme quotation.pdf', 'fld_quotations', 'type_doc', [240 * 1024]),
  file('Draft quote.pdf', 'fld_quotations', null, [120 * 1024, 132 * 1024]),
  file('Invoice INV-1042.pdf', 'fld_invoices', 'type_doc', [88 * 1024]),
  file('Venue floorplan.png', 'fld_events_2026', null, [1.4 * MB]),
  file('Run sheet.xlsx', 'fld_events_2026', 'type_sheet', [36 * 1024]),
  file('Welcome banner.jpg', null, null, [2.1 * MB]),
  file('Terms.docx', 'fld_contracts', 'type_doc', [54 * 1024]),
];

const types: AttachmentTypeRow[] = [
  type('type_doc', 'Document', 'PDFs and word documents', ['pdf', 'docx'], 25),
  type('type_image', 'Image', 'Photos and graphics', ['png', 'jpg', 'jpeg', 'webp'], 10),
  type('type_sheet', 'Spreadsheet', 'Tabular data', ['xlsx', 'csv'], 15),
];

const downloadJobs: DownloadJob[] = [
  {
    id: 'job_ready',
    filename: 'Quotations.zip',
    status: 'ready',
    fileCount: 2,
    error: null,
    createdAt: '2026-06-12T08:40:00Z',
    readyAt: '2026-06-12T08:40:09Z',
  },
];

let settings: DocumentSettings = {
  publicSharing: 'off',
  defaultMaxFileMb: 50,
  storageQuotaMb: 2048,
  usedBytes: 0,
};

function fld(id: string, parentId: string | null, name: string): FolderRec {
  return {
    id,
    parentId,
    name,
    createdBy: DEMO_USER,
    createdAt: NOW,
    updatedAt: NOW,
    deleted: false,
  };
}
function file(
  name: string,
  folderId: string | null,
  typeId: string | null,
  sizes: number[],
): FileRec {
  const id = nid('file');
  return {
    id,
    folderId,
    name,
    typeId,
    versions: sizes.map((sizeBytes, i) => ({
      id: nid('ver'),
      ordinal: i + 1,
      sizeBytes: Math.round(sizeBytes),
      mime: mimeOf(name),
      uploadedBy: DEMO_USER,
      createdAt: NOW,
    })),
    createdBy: DEMO_USER,
    createdAt: NOW,
    updatedAt: NOW,
    deleted: false,
  };
}
function type(
  id: string,
  name: string,
  description: string,
  allowedExts: string[],
  maxMb: number | null,
): AttachmentTypeRow {
  return {
    id,
    name,
    description,
    allowedExts,
    maxMb,
    fileCount: 0,
    createdAt: NOW,
    updatedAt: NOW,
  };
}

// ── Derivations ─────────────────────────────────────────────────────────────

const liveFolders = () => folders.filter((f) => !f.deleted);
const liveFiles = () => files.filter((f) => !f.deleted);
const folderById = (id: string) => folders.find((f) => f.id === id);
const currentVersion = (f: FileRec) => f.versions[f.versions.length - 1];

function usedBytes(): number {
  // Sum every retained version of every non-deleted file (history counts).
  return liveFiles().reduce(
    (sum, f) => sum + f.versions.reduce((s, v) => s + v.sizeBytes, 0),
    0,
  );
}

function breadcrumb(folderId: string | null): { id: string; name: string }[] {
  const crumbs: { id: string; name: string }[] = [];
  let cur = folderId ? folderById(folderId) : null;
  while (cur) {
    crumbs.unshift({ id: cur.id, name: cur.name });
    cur = cur.parentId ? folderById(cur.parentId) ?? null : null;
  }
  return crumbs;
}

function toFolderRow(f: FolderRec): FolderRow {
  return {
    id: f.id,
    parentId: f.parentId,
    name: f.name,
    path: breadcrumb(f.parentId),
    folderCount: liveFolders().filter((c) => c.parentId === f.id).length,
    fileCount: liveFiles().filter((c) => c.folderId === f.id).length,
    createdBy: f.createdBy,
    createdAt: f.createdAt,
    updatedAt: f.updatedAt,
  };
}

function toVersionRow(v: VersionRec): FileVersionRow {
  return {
    id: v.id,
    ordinal: v.ordinal,
    sizeBytes: v.sizeBytes,
    mime: v.mime,
    uploadedBy: v.uploadedBy,
    uploadedByName: DEMO_NAME,
    createdAt: v.createdAt,
  };
}

function toFileRow(f: FileRec): FileRow {
  const typeName = f.typeId ? types.find((t) => t.id === f.typeId)?.name ?? null : null;
  return {
    id: f.id,
    folderId: f.folderId,
    name: f.name,
    currentVersion: toVersionRow(currentVersion(f)),
    attachmentTypeId: f.typeId,
    attachmentTypeName: typeName,
    versionCount: f.versions.length,
    createdBy: f.createdBy,
    createdByName: DEMO_NAME,
    createdAt: f.createdAt,
    updatedAt: f.updatedAt,
  };
}

/** All descendant folder ids of `id` (inclusive) - for cascade + cycle guard. */
function subtreeFolderIds(id: string): Set<string> {
  const out = new Set<string>([id]);
  let added = true;
  while (added) {
    added = false;
    for (const f of folders) {
      if (f.parentId && out.has(f.parentId) && !out.has(f.id)) {
        out.add(f.id);
        added = true;
      }
    }
  }
  return out;
}

/** Auto-rename for Keep-both: "name.ext" → "name (1).ext", "(2)", … */
function uniqueName(folderId: string | null, name: string): string {
  const taken = new Set(
    liveFiles()
      .filter((f) => f.folderId === folderId)
      .map((f) => f.name.toLowerCase()),
  );
  if (!taken.has(name.toLowerCase())) return name;
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  for (let n = 1; n < 1000; n += 1) {
    const candidate = `${stem} (${n})${ext}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
  return `${stem} (${nid('x')})${ext}`;
}

// ── Resource-list helper (attachment types) ─────────────────────────────────

function applyTypeQuery(query: ListQuery): ListResult<AttachmentTypeRow> {
  let rows = types.map((t) => ({
    ...t,
    fileCount: liveFiles().filter((f) => f.typeId === t.id).length,
  }));
  const search = query.search?.trim().toLowerCase();
  if (search) {
    rows = rows.filter(
      (t) =>
        t.name.toLowerCase().includes(search) ||
        (t.description ?? '').toLowerCase().includes(search),
    );
  }
  if (query.sort) {
    const { id, desc } = query.sort;
    rows.sort((a, b) => {
      const av = String((a as Record<string, unknown>)[id] ?? '');
      const bv = String((b as Record<string, unknown>)[id] ?? '');
      return desc ? bv.localeCompare(av) : av.localeCompare(bv);
    });
  }
  const total = rows.length;
  const start = query.page * query.pageSize;
  return { data: clone(rows.slice(start, start + query.pageSize)), total, page: query.page };
}

// ── Service ─────────────────────────────────────────────────────────────────

export const mockDocumentService: DocumentService = {
  async listFolder(folderId) {
    const listing: FolderListing = {
      folder: folderId ? toFolderRow(folderById(folderId)!) : null,
      breadcrumb: breadcrumb(folderId),
      folders: liveFolders()
        .filter((f) => f.parentId === folderId)
        .map(toFolderRow)
        .sort((a, b) => a.name.localeCompare(b.name)),
      files: liveFiles()
        .filter((f) => f.folderId === folderId)
        .map(toFileRow)
        .sort((a, b) => a.name.localeCompare(b.name)),
    };
    return delay(clone(listing));
  },

  async createFolder({ parentId, name }: CreateFolderPayload) {
    const rec = fld(nid('fld'), parentId, name.trim() || 'Untitled folder');
    folders.push(rec);
    return delay(clone(toFolderRow(rec)));
  },

  async renameFolder(id, { name }: RenamePayload) {
    const rec = folderById(id);
    if (!rec) throw new Error('Folder not found');
    rec.name = name.trim() || rec.name;
    rec.updatedAt = NOW;
    return delay(clone(toFolderRow(rec)));
  },

  async moveFolders(ids, { targetFolderId }: MovePayload) {
    for (const id of ids) {
      const rec = folderById(id);
      if (!rec) continue;
      // Cycle guard: can't move a folder into itself or a descendant.
      if (targetFolderId && subtreeFolderIds(id).has(targetFolderId)) {
        throw new Error("Can't move a folder into itself.");
      }
      rec.parentId = targetFolderId;
      rec.updatedAt = NOW;
    }
    return delay(undefined);
  },

  async deleteFolders(ids) {
    for (const id of ids) {
      const subtree = subtreeFolderIds(id);
      folders.forEach((f) => {
        if (subtree.has(f.id)) f.deleted = true;
      });
      files.forEach((f) => {
        if (f.folderId && subtree.has(f.folderId)) f.deleted = true;
      });
    }
    return delay(undefined);
  },

  async renameFile(id, { name }: RenamePayload) {
    const rec = files.find((f) => f.id === id);
    if (!rec) throw new Error('File not found');
    rec.name = name.trim() || rec.name;
    rec.updatedAt = NOW;
    return delay(clone(toFileRow(rec)));
  },

  async moveFiles(ids, { targetFolderId }: MovePayload) {
    ids.forEach((id) => {
      const rec = files.find((f) => f.id === id);
      if (rec) {
        rec.folderId = targetFolderId;
        rec.updatedAt = NOW;
      }
    });
    return delay(undefined);
  },

  async deleteFiles(ids) {
    files.forEach((f) => {
      if (ids.includes(f.id)) f.deleted = true;
    });
    return delay(undefined);
  },

  async fileVersions(fileId) {
    const rec = files.find((f) => f.id === fileId);
    if (!rec) throw new Error('File not found');
    return delay(clone([...rec.versions].reverse().map(toVersionRow)));
  },

  async upload(file: File, options: UploadOptions, onProgress?: UploadProgress) {
    const ext = extOf(file.name);

    // 1. Sniff hard-floor - never overridable.
    if (BLOCKED_EXTS.has(ext)) {
      throw new UploadRejectedError(
        `${ext.toUpperCase()} files aren't allowed for security reasons.`,
      );
    }

    // 2. Size policy (per-type cap else tenant default).
    const type = options.attachmentTypeId
      ? types.find((t) => t.id === options.attachmentTypeId)
      : null;
    const capMb = type?.maxMb ?? settings.defaultMaxFileMb;
    if (file.size > capMb * MB) {
      throw new UploadRejectedError(
        `"${file.name}" is larger than the ${capMb} MB limit.`,
      );
    }
    if (type && type.allowedExts.length && !type.allowedExts.includes(ext)) {
      throw new UploadRejectedError(
        `${type.name} doesn't accept .${ext} files.`,
      );
    }

    // 3. Quota.
    if (settings.storageQuotaMb != null) {
      const replacing =
        options.conflict === 'replace'
          ? liveFiles().find(
              (f) =>
                f.folderId === options.folderId &&
                f.name.toLowerCase() === file.name.toLowerCase(),
            )
          : null;
      const freed = replacing ? 0 : 0; // replace still keeps old versions (D5)
      if (usedBytes() + file.size - freed > settings.storageQuotaMb * MB) {
        throw new StorageQuotaError();
      }
    }

    // 4. Collision.
    const existing = liveFiles().find(
      (f) =>
        f.folderId === options.folderId &&
        f.name.toLowerCase() === file.name.toLowerCase(),
    );

    // Simulate progress.
    if (onProgress) {
      for (const p of [15, 45, 75, 100]) {
        await delay(undefined, 90);
        onProgress(p);
      }
    }

    if (existing && !options.conflict) {
      throw new UploadConflictError({
        fileName: file.name,
        existingFileId: existing.id,
      });
    }

    if (existing && options.conflict === 'replace') {
      existing.versions.push({
        id: nid('ver'),
        ordinal: existing.versions.length + 1,
        sizeBytes: file.size,
        mime: mimeOf(file.name),
        uploadedBy: DEMO_USER,
        createdAt: NOW,
      });
      existing.updatedAt = NOW;
      if (options.attachmentTypeId !== undefined) existing.typeId = options.attachmentTypeId;
      return delay<UploadResult>({ file: clone(toFileRow(existing)) });
    }

    const name =
      existing && options.conflict === 'keep_both'
        ? uniqueName(options.folderId, file.name)
        : file.name;
    const rec: FileRec = {
      id: nid('file'),
      folderId: options.folderId,
      name,
      typeId: options.attachmentTypeId ?? null,
      versions: [
        {
          id: nid('ver'),
          ordinal: 1,
          sizeBytes: file.size,
          mime: mimeOf(file.name),
          uploadedBy: DEMO_USER,
          createdAt: NOW,
        },
      ],
      createdBy: DEMO_USER,
      createdAt: NOW,
      updatedAt: NOW,
      deleted: false,
    };
    files.push(rec);
    return delay<UploadResult>({ file: clone(toFileRow(rec)) });
  },

  async listTrash() {
    return delay({
      folders: clone(folders.filter((f) => f.deleted).map(toFolderRow)),
      files: clone(files.filter((f) => f.deleted).map(toFileRow)),
    });
  },

  async restoreFolders(ids) {
    // Restore the folder + its whole subtree (folders + their files).
    const restore = new Set<string>();
    ids.forEach((id) => subtreeFolderIds(id).forEach((s) => restore.add(s)));
    folders.forEach((f) => {
      if (restore.has(f.id)) f.deleted = false;
    });
    files.forEach((f) => {
      if (f.folderId && restore.has(f.folderId)) f.deleted = false;
    });
    return delay(undefined);
  },

  async restoreFiles(ids) {
    files.forEach((f) => {
      if (ids.includes(f.id)) f.deleted = false;
    });
    return delay(undefined);
  },

  async purgeFolders(ids) {
    const drop = new Set<string>();
    ids.forEach((id) => subtreeFolderIds(id).forEach((s) => drop.add(s)));
    for (let i = folders.length - 1; i >= 0; i -= 1) {
      if (drop.has(folders[i].id)) folders.splice(i, 1);
    }
    for (let i = files.length - 1; i >= 0; i -= 1) {
      if (files[i].folderId && drop.has(files[i].folderId!)) files.splice(i, 1);
    }
    return delay(undefined);
  },

  async purgeFiles(ids) {
    for (let i = files.length - 1; i >= 0; i -= 1) {
      if (ids.includes(files[i].id)) files.splice(i, 1);
    }
    return delay(undefined);
  },

  async previewUrl(fileId) {
    const rec = files.find((f) => f.id === fileId);
    if (!rec) throw new Error('File not found');
    const kind = previewKindOf(rec.name);
    if (kind === 'image') {
      // Deterministic placeholder image keyed by id (mock only).
      return delay(`https://picsum.photos/seed/${encodeURIComponent(rec.id)}/640/420`);
    }
    if (kind === 'pdf') {
      // Minimal inline PDF data URL so the sandboxed iframe renders something.
      const pdf =
        'data:application/pdf;base64,JVBERi0xLjQKJcfsj6IKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50IDE+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL01lZGlhQm94WzAgMCAyMDAgMjAwXT4+CmVuZG9iagp4cmVmCjAgNAowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2MCAwMDAwMCBuIAowMDAwMDAwMTExIDAwMDAwIG4gCnRyYWlsZXIKPDwvU2l6ZSA0L1Jvb3QgMSAwIFI+PgpzdGFydHhyZWYKMTkwCiUlRU9G';
      return delay(pdf);
    }
    throw new Error('No inline preview for this file type');
  },

  async downloadFile(fileId) {
    const rec = files.find((f) => f.id === fileId);
    if (!rec) throw new Error('File not found');
    return delay(new Blob([`mock bytes for ${rec.name}`], { type: mimeOf(rec.name) }));
  },

  async requestZip(req: ZipRequest) {
    const folderIds = req.folderIds ?? [];
    const fromFolders = folderIds.reduce((sum, fid) => {
      const sub = new Set<string>();
      subtreeFolderIds(fid).forEach((s) => sub.add(s));
      return sum + liveFiles().filter((f) => f.folderId && sub.has(f.folderId)).length;
    }, 0);
    const count = (req.fileIds?.length ?? 0) + fromFolders;
    const name =
      folderIds.length === 1 && !req.fileIds?.length
        ? `${folderById(folderIds[0])?.name ?? 'folder'}.zip`
        : `documents-${downloadJobs.length + 1}.zip`;
    const job: DownloadJob = {
      id: nid('job'),
      filename: name,
      status: 'pending',
      fileCount: count,
      error: null,
      createdAt: NOW,
      readyAt: null,
    };
    downloadJobs.unshift(job);
    // Simulate async progression.
    setTimeout(() => {
      job.status = 'processing';
    }, 400);
    setTimeout(() => {
      job.status = 'ready';
      job.readyAt = NOW;
    }, 1600);
    return delay(clone(job));
  },

  async listDownloadJobs() {
    return delay(clone(downloadJobs));
  },

  async downloadJobUrl(jobId) {
    const job = downloadJobs.find((j) => j.id === jobId);
    if (!job || job.status !== 'ready') throw new Error('Not ready');
    return delay({ url: `blob:mock/${jobId}`, filename: job.filename });
  },

  async listTypes(query) {
    return delay(applyTypeQuery(query));
  },

  async exportTypes(query) {
    const { data } = applyTypeQuery({ ...query, page: 0, pageSize: 10000 });
    const header = 'Name,Description,Allowed extensions,Max MB,Files';
    const lines = data.map((t) =>
      [t.name, t.description ?? '', t.allowedExts.join(' '), t.maxMb ?? '', t.fileCount]
        .map((v) => `"${String(v).replace(/"/g, '""')}"`)
        .join(','),
    );
    return delay([header, ...lines].join('\n'));
  },

  async getType(id) {
    const t = types.find((x) => x.id === id);
    if (!t) throw new Error('Type not found');
    return delay(clone({ ...t, fileCount: liveFiles().filter((f) => f.typeId === id).length }));
  },

  async createType(payload) {
    const t: AttachmentTypeRow = {
      id: nid('type'),
      fileCount: 0,
      createdAt: NOW,
      updatedAt: NOW,
      ...payload,
    };
    types.push(t);
    return delay(clone(t));
  },

  async updateType(id, payload) {
    const t = types.find((x) => x.id === id);
    if (!t) throw new Error('Type not found');
    Object.assign(t, payload, { updatedAt: NOW });
    return delay(clone(t));
  },

  async deleteType(id) {
    const i = types.findIndex((x) => x.id === id);
    if (i >= 0) types.splice(i, 1);
    return delay(undefined);
  },

  async getSettings() {
    return delay(clone({ ...settings, usedBytes: usedBytes() }));
  },

  async updateSettings(patch) {
    settings = { ...settings, ...patch };
    return delay(clone({ ...settings, usedBytes: usedBytes() }));
  },

  // ── Sharing (slice-05, Google model) - in-memory stub for unit tests ──
  async getTargetShare(kind, id) {
    const found = shares.find(
      (s) => s.targetKind === kind && s.targetId === id && !s.isDisabled,
    );
    return delay(found ? clone(found) : null);
  },
  async ensureShare(kind, id) {
    let row = shares.find((s) => s.targetKind === kind && s.targetId === id);
    if (row) {
      row.isDisabled = false;
      return delay(clone(row));
    }
    const token = nid('tok') + nid('tok');
    row = {
      id: nid('share'),
      targetKind: kind,
      targetId: id,
      targetName: null,
      generalAccess: 'restricted',
      capability: 'view',
      token,
      url: `http://localhost:8001/public/documents/${token}`,
      expiresAt: null,
      isExpired: false,
      hasPassword: false,
      maxUploads: null,
      maxTotalMb: null,
      isDisabled: false,
      people: [],
      createdBy: 'mock',
      createdByName: 'Mock User',
      createdAt: NOW,
    };
    shares.push(row);
    return delay(clone(row));
  },
  async updateShare(id, patch) {
    const row = shares.find((s) => s.id === id);
    if (!row) throw new Error('Share not found');
    if (patch.generalAccess !== undefined) row.generalAccess = patch.generalAccess;
    if (patch.capability !== undefined) row.capability = patch.capability;
    if (patch.expiresAt !== undefined) row.expiresAt = patch.expiresAt;
    if (patch.password !== undefined) row.hasPassword = !!patch.password;
    if (patch.maxUploads !== undefined) row.maxUploads = patch.maxUploads;
    if (patch.maxTotalMb !== undefined) row.maxTotalMb = patch.maxTotalMb;
    if (patch.isDisabled !== undefined) row.isDisabled = patch.isDisabled;
    if (patch.people !== undefined) {
      row.people = patch.people.map((p) => ({ id: p.userId, capability: p.capability }));
    }
    return delay(clone(row));
  },
  async revokeShares(ids) {
    shares.forEach((s) => {
      if (ids.includes(s.id)) s.isDisabled = true;
    });
    return delay(undefined);
  },
  async listSharedWithMe() {
    return delay([]);
  },
  async listShareUsers(search) {
    const all: ShareUser[] = [
      { id: 'u-1', name: 'Ada Lovelace', email: 'ada@example.com' },
      { id: 'u-2', name: 'Alan Turing', email: 'alan@example.com' },
    ];
    const q = (search ?? '').toLowerCase();
    return delay(all.filter((u) => !q || (u.name ?? '').toLowerCase().includes(q)));
  },
  async listShares(query, segment) {
    const rows = shares.filter((s) => (segment === 'revoked' ? s.isDisabled : !s.isDisabled));
    return delay({ data: rows.map(clone), total: rows.length, page: query.page });
  },
  async exportShares() {
    return delay('Target,Kind,Tier,Capability\n');
  },
  async resolveShareByToken() {
    return delay(null);
  },
  async shareFileBlobUrl() {
    return delay('blob:mock');
  },
  async downloadShareFile() {
    return delay(undefined);
  },
  async uploadShareFile() {
    return delay(undefined);
  },
};

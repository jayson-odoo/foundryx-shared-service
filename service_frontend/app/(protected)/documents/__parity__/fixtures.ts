/**
 * Fixed records for the documents pages' switch-off parity and both-looks
 * request tests (Foundryx UIUX, slice W3-DOCS).
 */
import type {
  AttachmentTypeRow,
  DocumentSettings,
  FileRow,
  FolderListing,
  FolderRow,
  ShareRow,
} from '@/types/documents';

export function folder(over: Partial<FolderRow> = {}): FolderRow {
  return {
    id: 'fld-1',
    parentId: null,
    name: 'Quotations',
    path: [],
    folderCount: 1,
    fileCount: 2,
    createdBy: 'u-1',
    createdAt: '2026-11-01T02:00:00Z',
    updatedAt: '2026-11-02T02:00:00Z',
    ...over,
  };
}

export function file(over: Partial<FileRow> = {}): FileRow {
  return {
    id: 'fil-1',
    folderId: null,
    name: 'invoice-2026-11.pdf',
    currentVersion: {
      id: 'ver-1',
      ordinal: 1,
      sizeBytes: 245760,
      mime: 'application/pdf',
      uploadedBy: 'u-1',
      uploadedByName: 'Kay Tan',
      createdAt: '2026-11-03T02:00:00Z',
    },
    attachmentTypeId: null,
    attachmentTypeName: null,
    versionCount: 1,
    createdBy: 'u-1',
    createdByName: 'Kay Tan',
    createdAt: '2026-11-03T02:00:00Z',
    updatedAt: '2026-11-03T02:00:00Z',
    ...over,
  };
}

export const ROOT_LISTING: FolderListing = {
  folder: null,
  breadcrumb: [],
  folders: [folder(), folder({ id: 'fld-2', name: 'Contracts', folderCount: 0, fileCount: 0 })],
  files: [file(), file({ id: 'fil-2', name: 'logo.png', currentVersion: { ...file().currentVersion, id: 'ver-2', mime: 'image/png', sizeBytes: 5120 } })],
};

export const SETTINGS: DocumentSettings = {
  publicSharing: 'view',
  defaultMaxFileMb: 25,
  storageQuotaMb: 2048,
  usedBytes: 52428800,
};

export const TRASH = {
  folders: [folder({ id: 'fld-9', name: 'Old drafts' })],
  files: [file({ id: 'fil-9', name: 'scan-0042.jpg' })],
};

export function share(over: Partial<ShareRow> = {}): ShareRow {
  return {
    id: 'shr-1',
    targetKind: 'folder',
    targetId: 'fld-1',
    targetName: 'Quotations',
    generalAccess: 'workspace',
    capability: 'view',
    token: 'tok-parity-0001',
    url: 'http://localhost:8001/public/documents/tok-parity-0001',
    expiresAt: '2027-01-15T23:59:59Z',
    isExpired: false,
    hasPassword: false,
    maxUploads: null,
    maxTotalMb: null,
    isDisabled: false,
    people: [{ id: 'u-2', name: 'Ada Lim', email: 'ada@example.com', capability: 'view' }],
    createdBy: 'u-1',
    createdByName: 'Kay Tan',
    createdAt: '2026-11-04T02:00:00Z',
    ...over,
  };
}

export const SHARES: ShareRow[] = [
  share(),
  share({ id: 'shr-2', targetKind: 'file', targetId: 'fil-1', targetName: 'invoice-2026-11.pdf', generalAccess: 'public', expiresAt: null, people: [] }),
  share({ id: 'shr-3', targetName: 'Contracts', targetId: 'fld-2', generalAccess: 'restricted', capability: 'edit', expiresAt: '2026-10-01T23:59:59Z', isExpired: true }),
];

export function docType(over: Partial<AttachmentTypeRow> = {}): AttachmentTypeRow {
  return {
    id: 'typ-1',
    name: 'Invoice',
    description: 'Supplier and customer invoices',
    allowedExts: ['pdf', 'png'],
    maxMb: 10,
    fileCount: 12,
    createdAt: '2026-11-01T02:00:00Z',
    updatedAt: '2026-11-01T02:00:00Z',
    ...over,
  };
}

export const TYPES: AttachmentTypeRow[] = [
  docType(),
  docType({ id: 'typ-2', name: 'Contract', description: null, allowedExts: [], maxMb: null, fileCount: 0 }),
];

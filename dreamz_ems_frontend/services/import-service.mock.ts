/** Mock import service (Phase A) — static config + a single in-memory job. */
import type { ImportConfig, ImportJob, ImportJobList, ImportPreview } from '@/types/import';
import type { CreateImportInput, ImportService } from './import-service';

const delay = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 150));

const CONFIG: ImportConfig = {
  entityType: 'user',
  label: 'User',
  columns: [
    { key: 'id', label: 'ID', type: 'string', required: false, unique: false, options: null, hasResolver: false },
    { key: 'email', label: 'Email', type: 'string', required: true, unique: true, options: null, hasResolver: false },
    { key: 'name', label: 'Name', type: 'string', required: false, unique: false, options: null, hasResolver: false },
    { key: 'status', label: 'Status', type: 'enum', required: false, unique: false, options: [{ value: 'ACTIVE', label: 'Active' }], hasResolver: false },
  ],
  modes: ['create_only', 'update_only', 'upsert'],
  contextKeys: [],
};

let job: ImportJob = {
  id: 'imp-mock-1', entityType: 'user', mode: 'create_only', status: 'validated',
  abortOnInvalid: false, triggerAutomations: false, sheetName: 'Sheet1',
  mapping: { Email: 'email', Name: 'name' }, context: null,
  totalRows: 5, validRows: 4, invalidRows: 1,
  errors: [{ row: 3, column: 'email', message: 'not a valid email address' }],
  hasErrorFile: true, createdIds: null, updatedIds: null, filesPurged: false,
  createdAt: new Date().toISOString(), finishedAt: null,
};

export const mockImportService: ImportService = {
  getConfig: () => delay(CONFIG),
  downloadTemplate: () => delay(new Blob(['Email,Name\n'], { type: 'text/csv' })),
  create: (_i: CreateImportInput) => delay({ jobId: job.id }),
  preview: () => delay<ImportPreview>({ sheets: ['Sheet1'], sheetName: 'Sheet1', headers: ['Email', 'Name'], autoMapping: { Email: 'email', Name: 'name' } }),
  setMapping: (_id, mapping, sheetName) => delay({ ...job, mapping, sheetName: sheetName ?? null, status: 'validated' }),
  commit: () => { job = { ...job, status: 'done', createdIds: ['u1', 'u2', 'u3', 'u4'] }; return delay(job); },
  get: () => delay(job),
  list: () => delay<ImportJobList>({ items: [job], total: 1, page: 0, pageSize: 25 }),
  downloadErrorFile: () => delay(new Blob(['row,_error\n3,email: invalid\n'], { type: 'text/csv' })),
  getSettings: () => delay({ maxRows: 10000, maxFileMb: 10, isDefault: true }),
  updateSettings: (maxRows: number, maxFileMb: number) =>
    delay({ maxRows, maxFileMb, isDefault: false }),
};

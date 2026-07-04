/** Import engine types (sprint-3/09, F8) — mirror of the backend wire schemas. */

export type ImportMode = 'create_only' | 'update_only' | 'upsert';

export type ImportStatus =
  | 'pending'
  | 'validating'
  | 'validated'
  | 'importing'
  | 'done'
  | 'failed';

export interface ImportColumnDef {
  key: string;
  label: string;
  type: string;
  required: boolean;
  unique: boolean;
  options: { value: string; label: string }[] | null;
  hasResolver: boolean;
}

export interface ImportConfig {
  entityType: string;
  label: string;
  columns: ImportColumnDef[];
  modes: ImportMode[];
  contextKeys: string[];
}

export interface ImportError {
  row: number;
  column: string;
  message: string;
}

export interface ImportJob {
  id: string;
  entityType: string;
  mode: ImportMode;
  status: ImportStatus;
  abortOnInvalid: boolean;
  triggerAutomations: boolean;
  sheetName: string | null;
  mapping: Record<string, string | null> | null;
  context: Record<string, unknown> | null;
  totalRows: number;
  validRows: number;
  invalidRows: number;
  errors: ImportError[] | null;
  hasErrorFile: boolean;
  createdIds: string[] | null;
  updatedIds: string[] | null;
  filesPurged: boolean;
  createdAt: string;
  finishedAt: string | null;
}

export interface ImportPreview {
  sheets: string[];
  sheetName: string | null;
  headers: string[];
  autoMapping: Record<string, string | null>;
}

export interface ImportJobList {
  items: ImportJob[];
  total: number;
  page: number;
  pageSize: number;
}

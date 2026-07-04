/**
 * Import service (sprint-3/09, F8) — the boundary the import wizard + drawer
 * talk to (via hooks). The interface IS the backend contract (plan 09).
 */
import type {
  ImportConfig,
  ImportJob,
  ImportJobList,
  ImportMode,
  ImportPreview,
} from '@/types/import';
import { realImportService } from './import-service.real';

export interface CreateImportInput {
  entityType: string;
  mode: ImportMode;
  abortOnInvalid: boolean;
  triggerAutomations: boolean;
  context?: Record<string, unknown>;
  file: File;
}

export interface ImportService {
  getConfig(entityType: string): Promise<ImportConfig>;
  /** Authed blob download (a bare URL can't carry the Bearer). */
  downloadTemplate(
    entityType: string,
    columns: string[],
    format: 'xlsx' | 'csv',
  ): Promise<Blob>;
  create(input: CreateImportInput): Promise<{ jobId: string }>;
  preview(jobId: string, sheet?: string): Promise<ImportPreview>;
  setMapping(
    jobId: string,
    mapping: Record<string, string | null>,
    sheetName?: string,
    /** Job-level context (e.g. Ticket mode) merged onto the job before Test. */
    context?: Record<string, unknown>,
  ): Promise<ImportJob>;
  commit(
    jobId: string,
    opts?: {
      abortOnInvalid?: boolean;
      triggerAutomations?: boolean;
      context?: Record<string, unknown>;
    },
  ): Promise<ImportJob>;
  get(jobId: string): Promise<ImportJob>;
  list(params?: {
    entityType?: string;
    status?: string;
    page?: number;
    pageSize?: number;
  }): Promise<ImportJobList>;
  downloadErrorFile(jobId: string): Promise<Blob>;
  getSettings(): Promise<ImportSettings>;
  updateSettings(maxRows: number, maxFileMb: number): Promise<ImportSettings>;
}

export interface ImportSettings {
  maxRows: number;
  maxFileMb: number;
  isDefault: boolean;
}

export const importService: ImportService = realImportService;

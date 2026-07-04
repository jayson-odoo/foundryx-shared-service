/** Real import service — talks to FastAPI via the shared api-client. */
import type {
  ImportConfig,
  ImportJob,
  ImportJobList,
  ImportPreview,
} from '@/types/import';
import { apiFetch, apiFetchBlob } from '@/lib/api-client';
import type { CreateImportInput, ImportService } from './import-service';

const q = (key: string) => encodeURIComponent(key);

export const realImportService: ImportService = {
  getConfig(entityType) {
    return apiFetch<ImportConfig>(`/imports/config/${q(entityType)}`);
  },
  downloadTemplate(entityType, columns, format) {
    const cols = columns.join(',');
    return apiFetchBlob(
      `/imports/template/${q(entityType)}?columns=${encodeURIComponent(cols)}&format=${format}`,
    );
  },
  create(input: CreateImportInput) {
    const form = new FormData();
    form.append('file', input.file);
    form.append('entityType', input.entityType);
    form.append('mode', input.mode);
    form.append('abortOnInvalid', String(input.abortOnInvalid));
    form.append('triggerAutomations', String(input.triggerAutomations));
    if (input.context) form.append('context', JSON.stringify(input.context));
    return apiFetch<{ jobId: string }>('/imports', { method: 'POST', body: form });
  },
  preview(jobId, sheet) {
    const s = sheet ? `?sheet=${encodeURIComponent(sheet)}` : '';
    return apiFetch<ImportPreview>(`/imports/${jobId}/preview${s}`);
  },
  setMapping(jobId, mapping, sheetName, context) {
    return apiFetch<ImportJob>(`/imports/${jobId}/mapping`, {
      method: 'PUT',
      body: JSON.stringify({
        mapping,
        sheetName: sheetName ?? null,
        context: context ?? null,
      }),
    });
  },
  commit(jobId, opts) {
    return apiFetch<ImportJob>(`/imports/${jobId}/commit`, {
      method: 'POST',
      body: JSON.stringify({
        abortOnInvalid: opts?.abortOnInvalid ?? null,
        triggerAutomations: opts?.triggerAutomations ?? null,
        context: opts?.context ?? null,
      }),
    });
  },
  get(jobId) {
    return apiFetch<ImportJob>(`/imports/${jobId}`);
  },
  list(params = {}) {
    const sp = new URLSearchParams();
    if (params.entityType) sp.set('entityType', params.entityType);
    if (params.status) sp.set('status', params.status);
    sp.set('page', String(params.page ?? 0));
    sp.set('page_size', String(params.pageSize ?? 25));
    return apiFetch<ImportJobList>(`/imports?${sp.toString()}`);
  },
  downloadErrorFile(jobId) {
    return apiFetchBlob(`/imports/${jobId}/errors-file`);
  },
  getSettings() {
    return apiFetch<import('./import-service').ImportSettings>('/imports/settings');
  },
  updateSettings(maxRows, maxFileMb) {
    return apiFetch<import('./import-service').ImportSettings>('/imports/settings', {
      method: 'PUT',
      body: JSON.stringify({ maxRows, maxFileMb }),
    });
  },
};

/**
 * Real respond.io migration service (plan 33 §5.2, as built across S1-S5).
 * S6 (AC-MIG-56) flips `respondio-migration-service.ts`'s shipped binding to
 * this file.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  CreateMigrationJobInput,
  MigrationJob,
  MigrationPreflight,
  MigrationSyncItem,
  MigrationSyncWebhook,
  MigrationUploadResult,
} from '@/types/respondio-migration';
import type { ListQuery, ListResult } from '@/types/resource';
import type { RespondioMigrationService } from './respondio-migration-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('pageSize', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sortBy', query.sort.id);
    p.set('sortDir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  if (query.segment && query.segment !== 'all') p.set('status', query.segment);
  return p;
}

export const realRespondioMigrationService: RespondioMigrationService = {
  preflight(connectionId, workspaceId) {
    const p = new URLSearchParams({ connectionId, workspaceId });
    return apiFetch<MigrationPreflight>(`/omnichannel/migration/preflight?${p.toString()}`);
  },
  uploadCsv(kind, file) {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    return apiFetch<MigrationUploadResult>('/omnichannel/migration/uploads', {
      method: 'POST',
      body: form,
    });
  },
  listJobs(query) {
    return apiFetch<ListResult<MigrationJob>>(`/omnichannel/migration/jobs?${listParams(query).toString()}`);
  },
  getJob(jobId) {
    return apiFetch<MigrationJob>(`/omnichannel/migration/jobs/${jobId}`);
  },
  createJob(input: CreateMigrationJobInput) {
    return apiFetch<MigrationJob>('/omnichannel/migration/jobs', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  cancelJob(jobId) {
    return apiFetch<MigrationJob>(`/omnichannel/migration/jobs/${jobId}/cancel`, { method: 'POST' });
  },
  downloadFailuresCsv(jobId) {
    return apiFetchText(`/omnichannel/migration/jobs/${jobId}/failures.csv`);
  },
  getSync(workspaceId) {
    const p = new URLSearchParams({ workspaceId });
    return apiFetch<MigrationSyncItem | null>(`/omnichannel/migration/syncs?${p.toString()}`);
  },
  createSync(workspaceId) {
    return apiFetch<MigrationSyncItem>('/omnichannel/migration/syncs', {
      method: 'POST',
      body: JSON.stringify({ workspaceId }),
    });
  },
  syncAction(id, action) {
    return apiFetch<MigrationSyncItem>(`/omnichannel/migration/syncs/${id}/${action}`, { method: 'POST' });
  },
  getSyncWebhook(id) {
    return apiFetch<MigrationSyncWebhook>(`/omnichannel/migration/syncs/${id}/webhook`);
  },
  rotateSyncWebhook(id) {
    return apiFetch<MigrationSyncWebhook>(`/omnichannel/migration/syncs/${id}/webhook/rotate`, {
      method: 'POST',
    });
  },
};

/**
 * Real respond.io migration service (plan 33 §5.2) - stubbed to the planned
 * routes ahead of the S1/S2 backend (S0 MOCK - swap the boundary in S6,
 * `respondio-migration-service.ts`). Not imported anywhere until S6 flips
 * the one line; kept here now so that swap really is one line, not a
 * from-scratch write under S6's time pressure.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  CreateMigrationJobInput,
  MigrationJob,
  MigrationPreflight,
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
  downloadFailuresCsv(jobId) {
    return apiFetchText(`/omnichannel/migration/jobs/${jobId}/failures.csv`);
  },
};

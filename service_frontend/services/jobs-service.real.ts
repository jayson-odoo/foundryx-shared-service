/** Real jobs service - talks to FastAPI via the shared api-client (`GET /jobs`,
 * `GET /jobs/{id}`, `POST /jobs/{id}/{abort,retry,complete}`). */
import { apiFetch } from '@/lib/api-client';
import type { Job, JobListResult } from '@/types/jobs';
import type { JobsService } from './jobs-service';

export const realJobsService: JobsService = {
  listJobs(query = {}) {
    const p = new URLSearchParams();
    if (query.type) p.set('type', query.type);
    if (query.status) p.set('status', query.status);
    p.set('page', String(query.page ?? 0));
    p.set('page_size', String(query.pageSize ?? 25));
    return apiFetch<JobListResult>(`/jobs?${p.toString()}`);
  },
  getJob(id) {
    return apiFetch<Job>(`/jobs/${id}`);
  },
  abortJob(id) {
    return apiFetch<Job>(`/jobs/${id}/abort`, { method: 'POST' });
  },
  retryJob(id) {
    return apiFetch<Job>(`/jobs/${id}/retry`, { method: 'POST' });
  },
  completeJob(id) {
    return apiFetch<Job>(`/jobs/${id}/complete`, { method: 'POST' });
  },
};

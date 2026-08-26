/**
 * Jobs service (sprint-4/10) - the boundary the Jobs drawer + `/jobs`
 * list/detail talk to (via hooks). Generic over job `type`; storage migration
 * is the first. The interface IS the backend contract (`app/api/v1/jobs.py`).
 *
 * Frontend-first: the UI iterates against `jobs-service.mock` (tunable
 * running/needs_review/failed/done states); the shipped boundary below is the
 * `.real` api-client impl - the mock/real swap is this one line.
 */
import type { Job, JobListQuery, JobListResult } from '@/types/jobs';
import { realJobsService } from './jobs-service.real';

export interface JobsService {
  /** Paginated, tenant-scoped job list (`GET /jobs`). */
  listJobs(query?: JobListQuery): Promise<JobListResult>;
  /** One job (`GET /jobs/{id}`). */
  getJob(id: string): Promise<Job>;
  /** Stop a running migration (`POST /jobs/{id}/abort`). */
  abortJob(id: string): Promise<Job>;
  /** Re-run a failed / needs-review migration (`POST /jobs/{id}/retry`). */
  retryJob(id: string): Promise<Job>;
  /** Accept a needs-review migration's failures + cutover (`.../complete`). */
  completeJob(id: string): Promise<Job>;
}

// Phase-B swap: the real api-client impl is the shipped boundary.
export const jobsService: JobsService = realJobsService;

/**
 * PHASE 1 MOCK jobs service (sprint-4/10) — an in-memory job store the wizard +
 * Jobs drawer iterate against with NO backend. A `running` job auto-advances its
 * progress on each `getJob`/`listJobs` poll (copying → done), so every state
 * (running / needs_review / failed / done / aborted) is exercisable. Tests seed
 * a controlled set via `seedMockJobs`.
 *
 * DEBT: the shipped boundary is `jobs-service.real`; this exists only for
 * frontend-first iteration + Vitest. Never wired into a "done" slice.
 */
import type { Job, JobListQuery, JobListResult, JobStatus } from '@/types/jobs';
import type { JobsService } from './jobs-service';

const delay = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 80));

function makeJob(over: Partial<Job> = {}): Job {
  const now = new Date().toISOString();
  return {
    id: `job-${Math.random().toString(36).slice(2, 8)}`,
    tenantId: 't-1',
    type: 'storage_migration',
    status: 'running',
    actorUserId: 'u-1',
    payload: { fromConnectionId: 'conn-a', toConnectionId: 'conn-b' },
    result: null,
    progressTotal: 20,
    progressDone: 4,
    progressFailed: 0,
    error: null,
    createdAt: now,
    startedAt: now,
    finishedAt: null,
    ...over,
  };
}

let _jobs: Job[] = [makeJob()];

/** Test/dev seam — replace the store with a controlled set of jobs. */
export function seedMockJobs(jobs: Job[]): void {
  _jobs = jobs.map((j) => ({ ...j }));
}

/** Advance a running job's copy progress; flip to `done` when it finishes. */
function tick(job: Job): Job {
  if (job.status !== 'running') return job;
  const done = Math.min(job.progressTotal, job.progressDone + 4);
  if (done >= job.progressTotal) {
    return {
      ...job,
      progressDone: job.progressTotal,
      status: 'done',
      finishedAt: new Date().toISOString(),
      result: { copied: job.progressTotal, failed: 0, orphaned: 0, failures: [] },
    };
  }
  return { ...job, progressDone: done };
}

export const mockJobsService: JobsService = {
  listJobs(query: JobListQuery = {}) {
    _jobs = _jobs.map(tick);
    let items = _jobs;
    if (query.type) items = items.filter((j) => j.type === query.type);
    if (query.status) items = items.filter((j) => j.status === (query.status as JobStatus));
    return delay<JobListResult>({ items: items.map((j) => ({ ...j })), total: items.length });
  },
  getJob(id) {
    _jobs = _jobs.map((j) => (j.id === id ? tick(j) : j));
    const job = _jobs.find((j) => j.id === id);
    if (!job) return Promise.reject(new Error('Job not found'));
    return delay({ ...job });
  },
  abortJob(id) {
    _jobs = _jobs.map((j) =>
      j.id === id ? { ...j, status: 'aborted', finishedAt: new Date().toISOString() } : j,
    );
    return delay({ ..._jobs.find((j) => j.id === id)! });
  },
  retryJob(id) {
    _jobs = _jobs.map((j) => (j.id === id ? { ...j, status: 'running', progressFailed: 0 } : j));
    return delay({ ..._jobs.find((j) => j.id === id)! });
  },
  completeJob(id) {
    _jobs = _jobs.map((j) =>
      j.id === id ? { ...j, status: 'done', finishedAt: new Date().toISOString() } : j,
    );
    return delay({ ..._jobs.find((j) => j.id === id)! });
  },
};

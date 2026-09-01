import { beforeEach, describe, expect, it } from 'vitest';
import {
  mockStorageMigrationService,
  setMockTestOutcome,
} from './storage-migration-service.mock';
import { mockJobsService, seedMockJobs } from './jobs-service.mock';
import type { Job } from '@/types/jobs';

function runningJob(): Job {
  const now = new Date().toISOString();
  return {
    id: 'job-x',
    tenantId: 't',
    type: 'storage_migration',
    status: 'running',
    actorUserId: null,
    payload: null,
    result: null,
    progressTotal: 8,
    progressDone: 0,
    progressFailed: 0,
    error: null,
    createdAt: now,
    startedAt: now,
    finishedAt: null,
  };
}

describe('mockStorageMigrationService (PHASE 1 MOCK)', () => {
  beforeEach(() => setMockTestOutcome({ ok: true, message: 'ok' }));

  it('testBucket() returns the tunable outcome', async () => {
    setMockTestOutcome({ ok: false, message: 'nope' });
    expect(await mockStorageMigrationService.testBucket({ provider: 's3', config: {}, credentials: {} })).toEqual(
      { ok: false, message: 'nope' },
    );
  });

  it('startMigration() returns a fresh pending job', async () => {
    const job = await mockStorageMigrationService.startMigration({
      provider: 's3',
      name: 'B',
      config: { bucket: 'b' },
      credentials: {},
    });
    expect(job.status).toBe('pending');
    expect(job.type).toBe('storage_migration');
  });
});

describe('mockJobsService (PHASE 1 MOCK) - auto-advancing progress', () => {
  it('a running job advances toward done across polls', async () => {
    seedMockJobs([runningJob()]);
    let job = await mockJobsService.getJob('job-x');
    expect(job.progressDone).toBeGreaterThan(0);
    // Poll until it settles.
    for (let i = 0; i < 5 && job.status === 'running'; i++) {
      job = await mockJobsService.getJob('job-x');
    }
    expect(job.status).toBe('done');
    expect(job.progressDone).toBe(job.progressTotal);
  });

  it('abort / retry / complete mutate state', async () => {
    seedMockJobs([runningJob()]);
    expect((await mockJobsService.abortJob('job-x')).status).toBe('aborted');
    expect((await mockJobsService.retryJob('job-x')).status).toBe('running');
    expect((await mockJobsService.completeJob('job-x')).status).toBe('done');
  });
});

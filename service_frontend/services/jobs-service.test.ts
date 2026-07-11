import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));

import { realJobsService } from './jobs-service.real';
import { realStorageMigrationService } from './storage-migration-service.real';

beforeEach(() => {
  vi.clearAllMocks();
  apiFetch.mockResolvedValue({});
});

describe('realJobsService', () => {
  it('listJobs() encodes type + status + pagination', async () => {
    await realJobsService.listJobs({ type: 'storage_migration', status: 'running', page: 2, pageSize: 50 });
    expect(apiFetch.mock.calls[0][0]).toBe(
      '/jobs?type=storage_migration&status=running&page=2&page_size=50',
    );
  });

  it('listJobs() defaults page 0 / size 25', async () => {
    await realJobsService.listJobs();
    expect(apiFetch.mock.calls[0][0]).toBe('/jobs?page=0&page_size=25');
  });

  it('getJob() hits the single-job endpoint', async () => {
    await realJobsService.getJob('j1');
    expect(apiFetch.mock.calls[0][0]).toBe('/jobs/j1');
  });

  it.each(['abort', 'retry', 'complete'] as const)('%s POSTs the control endpoint', async (op) => {
    const fn = { abort: 'abortJob', retry: 'retryJob', complete: 'completeJob' }[op] as
      | 'abortJob'
      | 'retryJob'
      | 'completeJob';
    await realJobsService[fn]('j9');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/jobs/j9/${op}`);
    expect(init.method).toBe('POST');
  });
});

describe('realStorageMigrationService', () => {
  it('testBucket() POSTs the non-destructive probe', async () => {
    await realStorageMigrationService.testBucket({
      provider: 's3',
      config: { bucket: 'b2' },
      credentials: { accessKeyId: 'k' },
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/storage/migrations/test');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      provider: 's3',
      config: { bucket: 'b2' },
      credentials: { accessKeyId: 'k' },
    });
  });

  it('startMigration() POSTs the start endpoint', async () => {
    await realStorageMigrationService.startMigration({
      provider: 's3',
      name: 'New bucket',
      config: { bucket: 'b2' },
      credentials: {},
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/storage/migrations');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).name).toBe('New bucket');
  });
});

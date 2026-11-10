/**
 * Mock respond.io migration service states (plan 33 S0, AC-MIG-09) - pins
 * the tunable job states (pending/running/needs_review/done/failed/aborted)
 * plus the `dry_run_required` / `migration_in_progress` guards (AC-MIG-20/21
 * mock-side enforcement) directly against `mockRespondioMigrationService`.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { MigrationJobStatus } from '@/types/respondio-migration';
import { __mockResetRespondioMigrations, mockRespondioMigrationService as svc } from './respondio-migration-service.mock';

beforeEach(() => {
  __mockResetRespondioMigrations();
});

describe('mockRespondioMigrationService - seeded states', () => {
  it('listJobs() seeds every MigrationJobStatus (AC-MIG-09)', async () => {
    const result = await svc.listJobs({ page: 0, pageSize: 25 });
    const statuses = new Set(result.data.map((j) => j.status));
    const expected: MigrationJobStatus[] = ['running', 'needs_review', 'done', 'failed', 'aborted'];
    for (const s of expected) expect(statuses.has(s)).toBe(true);
    expect(result.total).toBe(result.data.length);
  });

  it('listJobs() filters by segment (status)', async () => {
    const result = await svc.listJobs({ page: 0, pageSize: 25, segment: 'failed' });
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data.every((j) => j.status === 'failed')).toBe(true);
  });

  it('getJob() resolves a seeded job with its report inline', async () => {
    const { data } = await svc.listJobs({ page: 0, pageSize: 25, segment: 'done' });
    const one = await svc.getJob(data[0].id);
    expect(one.report).not.toBeNull();
  });

  it('getJob() 404s for an unknown id', async () => {
    await expect(svc.getJob('does-not-exist')).rejects.toBeInstanceOf(ApiError);
  });

  it('a failed/needs_review job carries a non-empty failureSample when failureCount > 0', async () => {
    const { data } = await svc.listJobs({ page: 0, pageSize: 25, segment: 'needs_review' });
    expect(data[0].failureCount).toBeGreaterThan(0);
    expect(data[0].failureSample.length).toBeGreaterThan(0);
  });

  it('downloadFailuresCsv() returns a header row plus one line per failure', async () => {
    const { data } = await svc.listJobs({ page: 0, pageSize: 25, segment: 'needs_review' });
    const csv = await svc.downloadFailuresCsv(data[0].id);
    const lines = csv.trim().split('\n');
    expect(lines[0]).toBe('entity,sourceId,sourceLabel,reason,action');
    expect(lines.length - 1).toBe(data[0].failureSample.length);
  });
});

describe('mockRespondioMigrationService - preflight', () => {
  it('preflight() 422s when either id is missing', async () => {
    await expect(svc.preflight('', 'wsp-001')).rejects.toMatchObject({ status: 422 });
    await expect(svc.preflight('conn-1', '')).rejects.toMatchObject({ status: 422 });
  });

  it('preflight() surfaces at least one source channel with no compatible target', async () => {
    const pf = await svc.preflight('conn-rio-mock-1', 'wsp-001');
    const targetTypes = new Set(pf.targetChannels.map((t) => t.channelType));
    const uncoveredSource = pf.channels.find((c) => c.source !== 'whatsapp_cloud');
    expect(uncoveredSource).toBeDefined();
    // 'instagram'/'telegram' sources map to types NOT present in targetChannels here.
    expect(targetTypes.has('INSTAGRAM')).toBe(false);
  });

  it('preflight() surfaces source lifecycle labels for the Lifecycle section', async () => {
    const pf = await svc.preflight('conn-rio-mock-1', 'wsp-001');
    expect(pf.lifecycles.length).toBeGreaterThan(0);
  });
});

describe('mockRespondioMigrationService - dry_run_required / migration_in_progress', () => {
  const baseInput = {
    connectionId: 'conn-rio-mock-1',
    workspaceId: 'wsp-001',
    source: 'api' as const,
    channelMap: [{ sourceChannelId: 'rio-chn-1', targetChannelId: 'chn-demo' }],
    userMap: [],
    teamMap: [],
    lifecycleMap: [],
    contactsOnly: false,
    messagesSince: null,
  };

  it('createJob(mode="run") 409s dry_run_required with no fresh matching dry run', async () => {
    // A workspace with no seeded in-flight job, so this isolates the
    // dry-run gate from the in-flight gate below.
    await expect(
      svc.createJob({ ...baseInput, workspaceId: 'wsp-002', mode: 'run' }),
    ).rejects.toMatchObject({
      status: 409,
      detail: { reason: 'dry_run_required' },
    });
  });

  it('createJob(mode="run") 409s migration_in_progress while a job is already in flight', async () => {
    // The seeded 'running' job already occupies (conn-rio-mock-1, wsp-001) -
    // checked BEFORE the dry-run gate, so this 409s even with no dry run.
    await expect(svc.createJob({ ...baseInput, mode: 'run' })).rejects.toMatchObject({
      status: 409,
      detail: { reason: 'migration_in_progress' },
    });
  });

  async function settleDryRun(input: typeof baseInput & { workspaceId: string }) {
    const dryRun = await svc.createJob({ ...input, mode: 'dry_run' });
    expect(dryRun.status).toBe('running');
    // Let the mock's setTimeout settle the dry run to 'done'.
    await new Promise((resolve) => setTimeout(resolve, 1600));
    const settled = await svc.getJob(dryRun.id);
    expect(settled.status).toBe('done');
  }

  it('a successful dry run unlocks Start migration for the EXACT same mapping', async () => {
    // wsp-002 - no seeded in-flight job (isolates the dry-run gate from the
    // in-flight gate exercised above).
    const input = { ...baseInput, workspaceId: 'wsp-002' };
    await settleDryRun(input);
    await expect(svc.createJob({ ...input, mode: 'run' })).resolves.toMatchObject({ mode: 'run' });
  });

  it('control: a DIFFERENT mapping stays locked even after a fresh dry run on the same workspace', async () => {
    // wsp-003 - its own workspace so the PRIOR test's now-`running` real run
    // never masks this as `migration_in_progress` instead of the intended
    // `dry_run_required`.
    const input = { ...baseInput, workspaceId: 'wsp-003' };
    await settleDryRun(input);
    const differentMapping = {
      ...input,
      mode: 'run' as const,
      channelMap: [...input.channelMap, { sourceChannelId: 'rio-chn-2', targetChannelId: null }],
    };
    await expect(svc.createJob(differentMapping)).rejects.toMatchObject({
      status: 409,
      detail: { reason: 'dry_run_required' },
    });
  });
});

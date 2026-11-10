/**
 * Migration job action registry (plan 33 S6, AC-MIG-57/58) - Abort is
 * visible only for an in-flight job, gated `omnichannel_migration.manage`,
 * and calls the DEDICATED cancel route directly (never the deferred
 * `jobs.abort` handler - see the hook's own docstring for why).
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { MigrationJob, MigrationJobStatus } from '@/types/respondio-migration';
import { useMigrationActions } from './use-migration-actions';

const cancelJobMock = vi.fn();
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: {
    cancelJob: (...args: unknown[]) => cancelJobMock(...args),
  },
}));

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function job(status: MigrationJobStatus, overrides: Partial<MigrationJob> = {}): MigrationJob {
  return {
    id: 'mig-job-1',
    mode: 'run',
    source: 'api',
    connectionId: 'conn-1',
    spaceLabel: 'Acme Support',
    workspaceId: 'wsp-1',
    workspaceName: 'Main workspace',
    status,
    progressTotal: 100,
    progressDone: 40,
    progressFailed: 0,
    entityCounts: { contacts: 40, messages: 0 },
    report: null,
    failureCount: 0,
    failureSample: [],
    startedAt: '2026-01-01T00:00:00Z',
    finishedAt: null,
    createdAt: '2026-01-01T00:00:00Z',
    actorUserName: 'Demo Admin',
    logs: [],
    ...overrides,
  };
}

function actionsFor() {
  const { result } = renderHook(() => useMigrationActions());
  return result.current;
}

describe('useMigrationActions - visibility + permission (AC-MIG-57/58)', () => {
  it('Abort is visible ONLY while the job is pending/running', () => {
    const actions = actionsFor();
    const abort = actions.find((a) => a.id === 'abort')!;
    expect(abort.isVisible!([job('pending')])).toBe(true);
    expect(abort.isVisible!([job('running')])).toBe(true);
    for (const status of ['needs_review', 'done', 'failed', 'aborted'] as MigrationJobStatus[]) {
      expect(abort.isVisible!([job(status)])).toBe(false);
    }
  });

  it('Abort is gated omnichannel_migration.manage', () => {
    const abort = actionsFor().find((a) => a.id === 'abort')!;
    expect(abort.permission).toBe('omnichannel_migration.manage');
  });

  it('is not a bulk action (a single in-flight selection only)', () => {
    const abort = actionsFor().find((a) => a.id === 'abort')!;
    expect(abort.isVisible!([job('running'), job('running', { id: 'mig-job-2' })])).toBe(false);
  });

  it('has no deferred grace window and no confirm dialog - a direct commit (S6 decision)', () => {
    const abort = actionsFor().find((a) => a.id === 'abort')!;
    expect(abort.deferred).toBeUndefined();
    expect(abort.confirm).toBeUndefined();
    expect(abort.run).toBeDefined();
  });

  it('Retry / Complete anyway are NOT registered (no real backend route exists for this job type)', () => {
    const actions = actionsFor();
    expect(actions.find((a) => a.id === 'retry')).toBeUndefined();
    expect(actions.find((a) => a.id === 'complete')).toBeUndefined();
  });
});

describe('useMigrationActions - run() against the real cancel route', () => {
  it('calls respondioMigrationService.cancelJob and reloads on success', async () => {
    cancelJobMock.mockResolvedValueOnce(job('aborted'));
    const abort = actionsFor().find((a) => a.id === 'abort')!;
    const reload = vi.fn();
    await abort.run!([job('running')], { reload });
    expect(cancelJobMock).toHaveBeenCalledWith('mig-job-1');
    expect(reload).toHaveBeenCalled();
  });

  it('a 409 not_in_progress is surfaced as friendly copy, not "Conflict"', async () => {
    const { toast } = await import('@/lib/toast');
    cancelJobMock.mockRejectedValueOnce(new ApiError('Conflict', 409, null, { reason: 'not_in_progress' }));
    const abort = actionsFor().find((a) => a.id === 'abort')!;
    const reload = vi.fn();
    await abort.run!([job('running')], { reload });
    expect(toast.error).toHaveBeenCalledWith('This migration already finished.');
    expect(reload).not.toHaveBeenCalled();
  });
});

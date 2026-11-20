import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MigrationSyncItem } from '@/types/respondio-migration';
import { ApiError } from '@/lib/api-client';
import {
  SYNC_POLL_IDLE_MS,
  SYNC_POLL_RUNNING_MS,
  syncErrorCopy,
  useMigrationSync,
} from './use-migration-sync';

const svc = vi.hoisted(() => ({
  getSync: vi.fn(),
  createSync: vi.fn(),
  syncAction: vi.fn(),
  getSyncWebhook: vi.fn(),
  rotateSyncWebhook: vi.fn(),
}));
const toastError = vi.hoisted(() => vi.fn());
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: svc,
}));
vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: toastError },
}));

function item(over: Partial<MigrationSyncItem> = {}): MigrationSyncItem {
  return {
    id: 's1',
    workspaceId: 'w1',
    status: 'active',
    pausedReason: null,
    intervalMinutes: 15,
    fullSweepHours: 6,
    lastSyncAt: null,
    nextSyncAt: null,
    lastFullSweepAt: null,
    runningJobId: null,
    lastError: null,
    lastResult: null,
    totals: null,
    sourceContactCount: null,
    estimatedFullSweepMinutes: null,
    sourceJobId: null,
    stoppedAt: null,
    createdAt: '2026-11-04T00:00:00Z',
    ...over,
  };
}

const conflict = (reason: string) => new ApiError('x', 409, null, { reason });

beforeEach(() => {
  Object.values(svc).forEach((f) => f.mockReset());
  toastError.mockReset();
  svc.getSync.mockResolvedValue(item());
  svc.getSyncWebhook.mockResolvedValue({ url: 'https://x.test/hook' });
});
afterEach(() => vi.useRealTimers());

describe('syncErrorCopy', () => {
  it('maps every 409 reason to plain copy', () => {
    for (const reason of [
      'tick_running',
      'sync_exists',
      'no_finished_migration',
      'webhook_unreadable',
      'migration_in_progress',
    ]) {
      const copy = syncErrorCopy(conflict(reason), 'fallback');
      expect(copy).not.toBe('fallback');
      expect(copy).not.toContain(reason);
    }
    expect(syncErrorCopy(conflict('something_new'), 'fallback')).toBe(
      'fallback',
    );
  });
});

describe('useMigrationSync', () => {
  it('toasts the plain copy when an action is refused', async () => {
    svc.syncAction.mockRejectedValue(conflict('tick_running'));
    const { result } = renderHook(() => useMigrationSync('w1', true));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.act('run-now');
    });
    expect(toastError).toHaveBeenCalledWith(
      syncErrorCopy(conflict('tick_running'), ''),
    );
  });

  it('keeps a single poll chain across actions', async () => {
    vi.useFakeTimers();
    svc.syncAction.mockResolvedValue(item({ runningJobId: 'j1' }));
    const { result } = renderHook(() => useMigrationSync('w1', true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(svc.getSync).toHaveBeenCalledTimes(1);
    await act(async () => {
      await result.current.act('run-now');
      await result.current.act('run-now');
    });
    svc.getSync.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SYNC_POLL_RUNNING_MS + 10);
    });
    expect(svc.getSync).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SYNC_POLL_RUNNING_MS * 3);
    });
    expect(svc.getSync.mock.calls.length).toBeLessThanOrEqual(4);
    expect(SYNC_POLL_IDLE_MS).toBeGreaterThan(SYNC_POLL_RUNNING_MS);
  });

  it('flags an unreadable webhook link and rotating replaces it', async () => {
    svc.getSyncWebhook.mockRejectedValue(conflict('webhook_unreadable'));
    svc.rotateSyncWebhook.mockResolvedValue({ url: 'https://x.test/new' });
    const { result } = renderHook(() => useMigrationSync('w1', true));
    await waitFor(() => expect(result.current.webhookUnreadable).toBe(true));
    expect(result.current.webhookUrl).toBeNull();
    await act(async () => {
      await result.current.rotateWebhook();
    });
    expect(svc.rotateSyncWebhook).toHaveBeenCalledWith('s1');
    expect(result.current.webhookUrl).toBe('https://x.test/new');
    expect(result.current.webhookUnreadable).toBe(false);
  });
});

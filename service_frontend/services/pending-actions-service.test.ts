/**
 * `pending-actions-service.real` hits the three routes exactly (AC-DLA-39/40);
 * `pending-actions-service.mock` (PHASE 1) supports the same contract with no
 * backend - idempotent re-park, conflict on a different key, and lazy commit
 * on `current()` once `commitAt` has passed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));

import { realPendingActionsService } from './pending-actions-service.real';
import {
  mockPendingActionsService,
  resetMockPendingActions,
  setMockWindowSeconds,
} from './pending-actions-service.mock';

beforeEach(() => {
  vi.clearAllMocks();
  apiFetch.mockResolvedValue({});
  resetMockPendingActions();
  setMockWindowSeconds('destructive', 10);
});

describe('realPendingActionsService', () => {
  it('park() POSTs /api/v1/pending-actions with the body shape', async () => {
    await realPendingActionsService.park('users.trash', 'user', 'u1', { note: 'x' });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/api/v1/pending-actions');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      actionKey: 'users.trash',
      entityType: 'user',
      entityId: 'u1',
      payload: { note: 'x' },
    });
  });

  it('cancel() POSTs the /{id}/cancel route', async () => {
    await realPendingActionsService.cancel('pa1');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/api/v1/pending-actions/pa1/cancel');
    expect(init.method).toBe('POST');
  });

  it('current() GETs with entityType/entityId query params', async () => {
    await realPendingActionsService.current('user', 'u1');
    expect(apiFetch.mock.calls[0][0]).toBe(
      '/api/v1/pending-actions/current?entityType=user&entityId=u1',
    );
  });
});

describe('mockPendingActionsService (PHASE 1 mock)', () => {
  it('park() then park() with the SAME key is idempotent (same id)', async () => {
    const first = await mockPendingActionsService.park('users.trash', 'user', 'u1');
    const second = await mockPendingActionsService.park('users.trash', 'user', 'u1');
    expect(second.id).toBe(first.id);
  });

  it('park() with a DIFFERENT key on the same record rejects', async () => {
    await mockPendingActionsService.park('users.trash', 'user', 'u2');
    await expect(mockPendingActionsService.park('templates.reset', 'user', 'u2')).rejects.toThrow();
  });

  it('current() lazily commits an overdue row', async () => {
    setMockWindowSeconds('destructive', 0.01);
    await mockPendingActionsService.park('users.trash', 'user', 'u3');
    await new Promise((r) => setTimeout(r, 20));
    const cur = await mockPendingActionsService.current('user', 'u3');
    expect(cur.pending).toBeNull();
    expect(cur.lastOutcome?.status).toBe('committed');
  });

  it('cancel() before the window closes clears pending, no outcome commit', async () => {
    const park = await mockPendingActionsService.park('users.trash', 'user', 'u4');
    await mockPendingActionsService.cancel(park.id);
    const cur = await mockPendingActionsService.current('user', 'u4');
    expect(cur.pending).toBeNull();
    expect(cur.lastOutcome?.status).toBe('cancelled');
  });
});

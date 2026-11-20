import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetchMock(...args) };
});

import { realRespondioMigrationService as svc } from './respondio-migration-service.real';

beforeEach(() => apiFetchMock.mockReset());

describe('realRespondioMigrationService sync routes (plan 52)', () => {
  it('hits the plan routes with the right verbs', async () => {
    apiFetchMock.mockResolvedValue(null);
    await svc.getSync('w1');
    expect(apiFetchMock).toHaveBeenLastCalledWith('/omnichannel/migration/syncs?workspaceId=w1');
    await svc.createSync('w1');
    expect(apiFetchMock).toHaveBeenLastCalledWith('/omnichannel/migration/syncs', {
      method: 'POST',
      body: JSON.stringify({ workspaceId: 'w1' }),
    });
    await svc.syncAction('s1', 'run-now');
    expect(apiFetchMock).toHaveBeenLastCalledWith('/omnichannel/migration/syncs/s1/run-now', { method: 'POST' });
    await svc.getSyncWebhook('s1');
    expect(apiFetchMock).toHaveBeenLastCalledWith('/omnichannel/migration/syncs/s1/webhook');
    await svc.rotateSyncWebhook('s1');
    expect(apiFetchMock).toHaveBeenLastCalledWith('/omnichannel/migration/syncs/s1/webhook/rotate', { method: 'POST' });
  });
});

import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import {
  __mockResetRespondioMigrations,
  __mockSetSync,
  mockRespondioMigrationService as svc,
} from './respondio-migration-service.mock';

const WS = 'wsp-001';

beforeEach(() => {
  __mockResetRespondioMigrations();
});

describe('mock sync service (PHASE 1 MOCK)', () => {
  it('getSync is null until created, create then conflicts (sync_exists)', async () => {
    expect(await svc.getSync(WS)).toBeNull();
    const created = await svc.createSync(WS);
    expect(created.status).toBe('active');
    await expect(svc.createSync(WS)).rejects.toMatchObject({ status: 409, detail: { reason: 'sync_exists' } });
    expect((await svc.getSync(WS))?.id).toBe(created.id);
  });

  it('create without a finished real API run is 409 no_finished_migration', async () => {
    await expect(svc.createSync('wsp-other')).rejects.toBeInstanceOf(ApiError);
    await expect(svc.createSync('wsp-other')).rejects.toMatchObject({ detail: { reason: 'no_finished_migration' } });
  });

  it('pause / resume / run-now / stop move the state; a running tick settles on the next read', async () => {
    const s = await svc.createSync(WS);
    expect((await svc.syncAction(s.id, 'pause')).status).toBe('paused');
    expect((await svc.syncAction(s.id, 'resume')).status).toBe('active');
    expect((await svc.syncAction(s.id, 'run-now')).runningJobId).not.toBeNull();
    await expect(svc.syncAction(s.id, 'run-now')).rejects.toMatchObject({ status: 409 });
    expect((await svc.getSync(WS))?.runningJobId).not.toBeNull();
    expect((await svc.getSync(WS))?.runningJobId).toBeNull();
    expect((await svc.syncAction(s.id, 'stop')).status).toBe('stopping');
    await svc.getSync(WS);
    const stopped = await svc.getSync(WS);
    expect(stopped?.status).toBe('stopped');
    expect(stopped?.stoppedAt).not.toBeNull();
  });

  it('a stopped sync restarts on the same row', async () => {
    __mockSetSync(WS, { status: 'stopped', stoppedAt: new Date().toISOString() });
    const before = await svc.getSync(WS);
    const again = await svc.createSync(WS);
    expect(again.id).toBe(before?.id);
    expect(again.status).toBe('active');
  });

  it('webhook URL rotates', async () => {
    const s = await svc.createSync(WS);
    const a = await svc.getSyncWebhook(s.id);
    const b = await svc.rotateSyncWebhook(s.id);
    expect(b.url).not.toBe(a.url);
  });
});

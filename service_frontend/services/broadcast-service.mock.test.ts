/**
 * Mock broadcast service states (tester defect D-6, plan 29 review round 1,
 * AC-BRD-13/AC-BRD-52) - `broadcast-service.mock.ts` (S0's scaffolding) had
 * no test file at all. It is no longer imported by anything since S4 bound
 * `broadcastService` to the real backend implementation (dead code, a
 * cleanup candidate per the test report's AC-BRD-13 remark) - this file
 * pins its behavior directly against the exported `mockBroadcastService`
 * so the states AC-BRD-13's manual S0 walkthrough covered (loading/empty/
 * Draft/Scheduled/Sending/Sent-with-failures/Cancelled, plus the 409/422
 * error states) have an actual automated test, whichever way the file's
 * future (kept vs deleted) is decided.
 */
import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { BroadcastStatus } from '@/types/omnichannel';
import { mockBroadcastService } from './broadcast-service.mock';

const WS = 'ws-mock';

describe('mockBroadcastService - seeded states', () => {
  it('list() seeds one broadcast per BroadcastStatus (every status view has content)', async () => {
    const result = await mockBroadcastService.list(WS, { page: 0, pageSize: 25 });
    const statuses = new Set(result.data.map((b) => b.status));
    const expected: BroadcastStatus[] = ['DRAFT', 'SCHEDULED', 'SENDING', 'SENT', 'CANCELLED', 'FAILED'];
    for (const s of expected) expect(statuses.has(s)).toBe(true);
    expect(result.total).toBe(result.data.length);
  });

  it('list() filters by segment (status view)', async () => {
    const result = await mockBroadcastService.list(WS, { page: 0, pageSize: 25, segment: 'DRAFT' });
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data.every((b) => b.status === 'DRAFT')).toBe(true);
  });

  it('get() resolves a seeded broadcast by id', async () => {
    const { data } = await mockBroadcastService.list(WS, { page: 0, pageSize: 1 });
    const one = await mockBroadcastService.get(WS, data[0].id);
    expect(one.id).toBe(data[0].id);
  });

  it('get() throws a 404 ApiError for an unknown id', async () => {
    await expect(mockBroadcastService.get(WS, 'no-such-id')).rejects.toMatchObject({ status: 404 });
  });

  it('recipients() supports state + search filtering on the SENDING broadcast (40 recipients)', async () => {
    const { data: broadcasts } = await mockBroadcastService.list(WS, { page: 0, pageSize: 25, segment: 'SENDING' });
    const sending = broadcasts[0];
    const all = await mockBroadcastService.recipients(WS, sending.id, { page: 0, pageSize: 100 });
    expect(all.total).toBeGreaterThan(0);
    const queued = await mockBroadcastService.recipients(WS, sending.id, { page: 0, pageSize: 100, state: 'queued' });
    expect(queued.data.every((r) => r.state === 'queued')).toBe(true);
    expect(queued.total).toBeLessThan(all.total);
  });
});

describe('mockBroadcastService - error states', () => {
  it('create() rejects with a 422 fieldErrors body when required fields are missing', async () => {
    await expect(
      mockBroadcastService.create(WS, {
        name: '',
        labels: [],
        channelId: '',
        templateId: '',
        audience: { kind: 'contacts', contactIds: [] },
        bindings: { header: [], body: [], buttons: [] },
      }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(422);
      const fieldErrors = (apiErr.detail as { fieldErrors?: Record<string, string> } | null)?.fieldErrors;
      expect(fieldErrors?.name).toBeTruthy();
      expect(fieldErrors?.channelId).toBeTruthy();
      expect(fieldErrors?.templateId).toBeTruthy();
      return true;
    });
  });

  it('remove() rejects with a 409 conflict on a non-Draft broadcast', async () => {
    const { data } = await mockBroadcastService.list(WS, { page: 0, pageSize: 25, segment: 'SENT' });
    await expect(mockBroadcastService.remove(WS, data[0].id)).rejects.toMatchObject({
      status: 409,
      detail: { reason: 'broadcast_not_editable' },
    });
  });

  it('cancel() rejects with a 409 conflict on a terminal (SENT) broadcast', async () => {
    const { data } = await mockBroadcastService.list(WS, { page: 0, pageSize: 25, segment: 'SENT' });
    await expect(mockBroadcastService.cancel(WS, data[0].id)).rejects.toMatchObject({
      status: 409,
      detail: { reason: 'broadcast_not_cancellable' },
    });
  });

  it('testSend() rejects with a 422 when no contact is chosen', async () => {
    const { data } = await mockBroadcastService.list(WS, { page: 0, pageSize: 1 });
    await expect(mockBroadcastService.testSend(WS, data[0].id, '')).rejects.toMatchObject({ status: 422 });
  });
});

describe('mockBroadcastService - duplicate (draft copy, D-A4-2)', () => {
  it('duplicate() creates a new DRAFT copy with a de-duplicated "(copy)" name', async () => {
    const { data } = await mockBroadcastService.list(WS, { page: 0, pageSize: 25, segment: 'SENT' });
    const source = data[0];
    const copy = await mockBroadcastService.duplicate(WS, source.id);
    expect(copy.id).not.toBe(source.id);
    expect(copy.status).toBe('DRAFT');
    expect(copy.name).toContain('(copy');
  });
});

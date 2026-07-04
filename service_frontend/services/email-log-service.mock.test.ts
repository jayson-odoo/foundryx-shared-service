/**
 * Mock email-log service — D14 semantics the Phase-B backend must mirror:
 * segment filtering, retry only FAILED|CANCELLED (attempts preserved),
 * cancel only PENDING (atomic guard), cancelled rows retryable.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import type { ListQuery } from '@/types/resource';
import { __resetMockEmailLog, mockEmailLogService as svc } from './email-log-service.mock';

const query = (segment?: string): ListQuery => ({ page: 0, pageSize: 50, segment });

async function rowWithStatus(status: string) {
  const { data } = await svc.list(query());
  const row = data.find((r) => r.status === status);
  if (!row) throw new Error(`no seeded row with status ${status}`);
  return row;
}

describe('mock email-log service (D14 contract)', () => {
  beforeEach(() => {
    __resetMockEmailLog();
  });

  it('segments filter by status; "all" returns everything', async () => {
    const all = await svc.list(query('all'));
    const failed = await svc.list(query('failed'));
    expect(failed.data.length).toBeGreaterThan(0);
    expect(failed.data.every((r) => r.status === 'FAILED')).toBe(true);
    expect(all.total).toBeGreaterThan(failed.total);
  });

  it('retry: FAILED → PENDING with attempts preserved (history honest)', async () => {
    const failed = await rowWithStatus('FAILED');
    const before = failed.attempts;
    const retried = await svc.retry(failed.id);
    expect(retried.status).toBe('PENDING');
    expect(retried.attempts).toBe(before);
    expect(retried.nextAttemptAt).toBeTruthy();
  });

  it('retry rejects SENT/PENDING rows', async () => {
    const sent = await rowWithStatus('SENT');
    await expect(svc.retry(sent.id)).rejects.toThrow(/failed or cancelled/i);
    const pending = await rowWithStatus('PENDING');
    await expect(svc.retry(pending.id)).rejects.toThrow(/failed or cancelled/i);
  });

  it('cancel: PENDING → CANCELLED; claimed/sent rows refuse (atomic guard)', async () => {
    const pending = await rowWithStatus('PENDING');
    const cancelled = await svc.cancel(pending.id);
    expect(cancelled.status).toBe('CANCELLED');

    const sending = await rowWithStatus('SENDING');
    await expect(svc.cancel(sending.id)).rejects.toThrow(/too late/i);
    const sent = await rowWithStatus('SENT');
    await expect(svc.cancel(sent.id)).rejects.toThrow(/too late/i);
  });

  it('cancelled rows are retryable end-to-end (user mandate)', async () => {
    const pending = await rowWithStatus('PENDING');
    await svc.cancel(pending.id);
    const retried = await svc.retry(pending.id);
    expect(retried.status).toBe('PENDING');
  });

  it('detail exposes body + error fields', async () => {
    const failed = await rowWithStatus('FAILED');
    const detail = await svc.get(failed.id);
    expect(detail?.htmlBody).toContain('<html');
    expect(detail?.textBody.length).toBeGreaterThan(0);
    expect(detail?.lastError).toMatch(/SMTP/);
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchText = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiFetchText: (...a: unknown[]) => apiFetchText(...a),
}));

import { emsService } from './ems-service';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('emsService void / refund (AC-05-TKT-04)', () => {
  it('voidTicket POSTs the void endpoint', async () => {
    apiFetch.mockResolvedValue({ ticketId: 'tk1', status: 'void', qrRotated: true, seatReleased: true });
    const res = await emsService.voidTicket('p1', 'tk1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/tickets/tk1/void');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(res).toMatchObject({ status: 'void', qrRotated: true, seatReleased: true });
  });

  it('refundTicket POSTs the refund endpoint', async () => {
    apiFetch.mockResolvedValue({ ticketId: 'tk1', status: 'refunded', qrRotated: true, seatReleased: false });
    const res = await emsService.refundTicket('p1', 'tk1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/tickets/tk1/refund');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(res.status).toBe('refunded');
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));

import { realNumberingService } from './numbering-service.real';

beforeEach(() => {
  vi.clearAllMocks();
  apiFetch.mockResolvedValue(undefined);
});

describe('realNumberingService', () => {
  it('getCatalog() GETs /numbering', async () => {
    apiFetch.mockResolvedValueOnce([]);
    await realNumberingService.getCatalog();
    expect(apiFetch).toHaveBeenCalledWith('/numbering');
  });

  it('setFormat() PUTs /numbering/{docType} with the body', async () => {
    await realNumberingService.setFormat('invoice', {
      prefix: 'INV-',
      formatPattern: '{prefix}{YYYY}-{NNNN}',
      reset: 'yearly',
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/numbering/invoice');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      prefix: 'INV-',
      formatPattern: '{prefix}{YYYY}-{NNNN}',
      reset: 'yearly',
    });
  });

  it('setNextVal() PUTs /numbering/{docType}/next-val', async () => {
    await realNumberingService.setNextVal('invoice', 42);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/numbering/invoice/next-val');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ nextVal: 42 });
  });

  it('resetFormat() DELETEs /numbering/{docType}', async () => {
    await realNumberingService.resetFormat('invoice');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/numbering/invoice');
    expect(init.method).toBe('DELETE');
  });

  it('encodes the docType in the path', async () => {
    await realNumberingService.resetFormat('a/b');
    expect(apiFetch.mock.calls[0][0]).toBe('/numbering/a%2Fb');
  });
});

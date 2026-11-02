import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchBlob = vi.fn();
vi.mock('@/lib/api-client', async (orig) => ({
  ...(await orig<typeof import('@/lib/api-client')>()),
  apiFetchBlob: (...a: unknown[]) => apiFetchBlob(...a),
}));
vi.mock('next-auth/react', () => ({ getSession: vi.fn() }));

import { realDocumentService } from './document-service.real';

/** A blob whose reported type is exactly `type` (the Blob ctor would lowercase it). */
function served(type: string): Blob {
  const b = new Blob(['x']);
  Object.defineProperty(b, 'type', { value: type });
  return b;
}

let created: Blob[];
beforeEach(() => {
  created = [];
  URL.createObjectURL = vi.fn((b: Blob) => {
    created.push(b);
    return 'blob:test';
  });
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.clearAllMocks());

const UNLISTED = ['text/html', 'image/svg+xml', 'application/xhtml+xml', 'TEXT/HTML', 'text/html;x=1', ''];
const ALLOWED: Array<[string, string]> = [
  ['image/png', 'image/png'],
  ['image/jpeg', 'image/jpeg'],
  ['application/pdf', 'application/pdf'],
  ['IMAGE/PNG', 'image/png'],
];

describe('document drive preview blob type (AC-52-01)', () => {
  for (const [name, call] of [
    ['previewUrl', () => realDocumentService.previewUrl('f1')],
    ['shareFileBlobUrl', () => realDocumentService.shareFileBlobUrl('tok', 'f1')],
  ] as const) {
    describe(name, () => {
      it.each(UNLISTED)('never renders a blob typed %j', async (type) => {
        apiFetchBlob.mockResolvedValue(served(type));
        await call();
        expect(created).toHaveLength(1);
        expect(created[0].type).toBe('application/octet-stream');
      });

      it.each(ALLOWED)('control: %s still previews', async (type, expected) => {
        apiFetchBlob.mockResolvedValue(served(type));
        await call();
        expect(created[0].type).toBe(expected);
      });
    });
  }
});

describe('download-only paths unchanged (AC-52-03)', () => {
  it('downloadFile returns the fetched blob untouched', async () => {
    const b = served('text/html');
    apiFetchBlob.mockResolvedValue(b);
    expect(await realDocumentService.downloadFile('f1')).toBe(b);
    expect(created).toHaveLength(0);
  });

  it('downloadShareFile keeps the stored bytes and type for the saved file', async () => {
    const b = served('text/html');
    apiFetchBlob.mockResolvedValue(b);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await realDocumentService.downloadShareFile('tok', 'f1', 'report.html');
    expect(created).toEqual([b]);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { publicShareService } from './public-share-service';

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
afterEach(() => vi.restoreAllMocks());

function respondWith(blob: Blob) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => blob }));
}

const UNLISTED = ['text/html', 'image/svg+xml', 'application/xhtml+xml', 'TEXT/HTML', 'text/html;x=1', ''];

describe('public share preview blob type (AC-52-01)', () => {
  it.each(UNLISTED)('never renders a blob typed %j', async (type) => {
    respondWith(served(type));
    await publicShareService.fileBlobUrl('tok', 'f1');
    expect(created).toHaveLength(1);
    expect(created[0].type).toBe('application/octet-stream');
  });

  it.each([
    ['image/png', 'image/png'],
    ['image/jpeg', 'image/jpeg'],
    ['application/pdf', 'application/pdf'],
    ['IMAGE/PNG', 'image/png'],
  ])('control: %s still previews', async (type, expected) => {
    respondWith(served(type));
    await publicShareService.fileBlobUrl('tok', 'f1');
    expect(created[0].type).toBe(expected);
  });
});

describe('public share one type list (AC-52-05)', () => {
  it('video/mp4 keeps its type', async () => {
    respondWith(served('video/mp4'));
    await publicShareService.fileBlobUrl('tok', 'f1');
    expect(created[0].type).toBe('video/mp4');
  });
});

describe('public share download unchanged (AC-52-03)', () => {
  it('download keeps the stored bytes and type for the saved file', async () => {
    const b = served('text/html');
    respondWith(b);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await publicShareService.download('tok', 'f1', 'report.html');
    expect(created).toEqual([b]);
  });
});

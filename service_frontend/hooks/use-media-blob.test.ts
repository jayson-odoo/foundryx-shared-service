import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const apiFetchBlob = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetchBlob: (...a: unknown[]) => apiFetchBlob(...a),
}));

import { useMediaBlob } from './use-media-blob';

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

async function load(type: string) {
  apiFetchBlob.mockResolvedValue(served(type));
  const { result } = renderHook(() => useMediaBlob('/conversations/c1/messages/m1/media'));
  await waitFor(() => expect(result.current.url).toBe('blob:test'));
  return created[0];
}

const UNLISTED = ['text/html', 'image/svg+xml', 'application/xhtml+xml', 'TEXT/HTML', 'text/html;x=1', ''];

describe('conversation media blob type (AC-52-04)', () => {
  it.each(UNLISTED)('a stored %j type becomes a download type', async (type) => {
    expect((await load(type)).type).toBe('application/octet-stream');
  });

  it.each([
    ['audio/ogg', 'audio/ogg'],
    ['audio/mpeg', 'audio/mpeg'],
    ['video/mp4', 'video/mp4'],
    ['image/jpeg', 'image/jpeg'],
    ['application/pdf', 'application/pdf'],
    ['IMAGE/JPEG', 'image/jpeg'],
  ])('control: %s keeps its type', async (type, expected) => {
    expect((await load(type)).type).toBe(expected);
  });

  it('a type off the audio/video/image lists is not kept', async () => {
    expect((await load('audio/x-unlisted-test')).type).toBe('application/octet-stream');
    expect((await load('video/x-unlisted-test')).type).toBe('application/octet-stream');
  });

  it('an optimistic local blob: url is used directly (unchanged)', async () => {
    const { result } = renderHook(() => useMediaBlob('blob:local'));
    await waitFor(() => expect(result.current.url).toBe('blob:local'));
    expect(apiFetchBlob).not.toHaveBeenCalled();
  });
});

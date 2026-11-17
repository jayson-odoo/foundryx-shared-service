import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { isCommentPostResult, uploadFailureReason, uploadInOrder } from './upload-files';

const f = (name: string) => new File(['x'], name, { type: 'image/png' });

describe('uploadInOrder', () => {
  it('uploads in order and returns only the files that failed', async () => {
    const order: string[] = [];
    const upload = vi.fn(async (file: File) => {
      order.push(file.name);
      if (file.name === 'b.png') throw new Error('boom');
    });
    const failed = await uploadInOrder([f('a.png'), f('b.png'), f('c.png')], upload);
    expect(order).toEqual(['a.png', 'b.png', 'c.png']);
    expect(failed.map((x) => x.file.name)).toEqual(['b.png']);
    expect(failed[0].reason).toBe('b.png did not upload');
  });

  it('recognises a comment post result', () => {
    expect(isCommentPostResult({ commentId: 'c', failed: [] })).toBe(true);
    expect(isCommentPostResult([])).toBe(false);
    expect(isCommentPostResult(undefined)).toBe(false);
  });
});

describe('uploadFailureReason', () => {
  const err = (status: number, message = 'm') => new ApiError(message, status);
  it.each([
    [err(415), "a.png: this file type can't be attached"],
    [err(413), 'a.png is too large (max 25 MB)'],
    [err(422, 'This comment has reached its attachment limit.'), 'This comment has reached its attachment limit.'],
    [err(429), 'Too many uploads. Try again later.'],
    [err(500), 'a.png did not upload'],
    [new Error('boom'), 'a.png did not upload'],
  ])('%#', (e, expected) => {
    expect(uploadFailureReason('a.png', e)).toBe(expected);
  });
});

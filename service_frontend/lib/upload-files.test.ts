import { describe, expect, it, vi } from 'vitest';
import { isCommentPostResult, uploadInOrder } from './upload-files';

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
    expect(failed.map((x) => x.name)).toEqual(['b.png']);
  });

  it('recognises a comment post result', () => {
    expect(isCommentPostResult({ commentId: 'c', failed: [] })).toBe(true);
    expect(isCommentPostResult([])).toBe(false);
    expect(isCommentPostResult(undefined)).toBe(false);
  });
});

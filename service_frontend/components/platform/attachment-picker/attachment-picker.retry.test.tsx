import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useAttachmentDraft, useUploadRetry } from './attachment-picker';

const f = (name: string) => new File(['x'], name, { type: 'text/plain' });

describe('useUploadRetry', () => {
  it('failed files stay in the draft, later additions stay too, and a removed one leaves', () => {
    const { result } = renderHook(() => {
      const draft = useAttachmentDraft();
      return { draft, uploads: useUploadRetry(draft, vi.fn()) };
    });
    const [ok, bad, later] = [f('ok.txt'), f('bad.txt'), f('later.txt')];
    act(() => result.current.draft.add([ok, bad]));
    const sent = result.current.draft.files;
    act(() => result.current.draft.add([later]));
    act(() => result.current.uploads.track({ commentId: 'c1', failed: [{ file: bad, reason: 'bad.txt did not upload' }] }, sent));
    expect(result.current.draft.files.map((x) => x.name)).toEqual(['bad.txt', 'later.txt']);
    expect(result.current.uploads.pending?.failed).toHaveLength(1);
    act(() => result.current.uploads.removeFailed(bad));
    expect(result.current.uploads.pending).toBeNull();
    expect(result.current.draft.files.map((x) => x.name)).toEqual(['later.txt']);
  });

  it('a retry keeps files added meanwhile and clears the ones that went through', async () => {
    const retry = vi.fn().mockResolvedValue([]);
    const { result } = renderHook(() => {
      const draft = useAttachmentDraft();
      return { draft, uploads: useUploadRetry(draft, retry) };
    });
    const bad = f('bad.txt');
    act(() => result.current.draft.add([bad]));
    act(() => result.current.uploads.track({ commentId: 'c1', failed: [{ file: bad, reason: 'r' }] }, [bad]));
    act(() => result.current.draft.add([f('later.txt')]));
    await act(async () => result.current.uploads.retryNow());
    expect(retry).toHaveBeenCalledWith('c1', [bad]);
    expect(result.current.uploads.pending).toBeNull();
    expect(result.current.draft.files.map((x) => x.name)).toEqual(['later.txt']);
  });
});

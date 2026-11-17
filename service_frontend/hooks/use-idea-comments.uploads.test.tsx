/** FEEDBACK-ATTACH-IMAGE fix round 1: staff comment uploads report failures and retry only those. */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { IdeaComment } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { useIdeaComments } from './use-idea-comments';

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }));

const file = (name: string) => new File(['x'], name, { type: 'text/plain' });
const created = { id: 'new1' } as IdeaComment;

function setup(upload: ReturnType<typeof vi.fn>) {
  const service = {
    listComments: vi.fn().mockResolvedValue([]),
    addComment: vi.fn().mockResolvedValue(created),
    uploadAttachment: upload,
  } as unknown as IdeaService;
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <IdeationRuntimeProvider
      runtime={{ mode: 'operator', service, paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' } }}
    >
      {children}
    </IdeationRuntimeProvider>
  );
  return { service, wrapper };
}

describe('useIdeaComments uploads', () => {
  it('add reports the files that failed; retryUploads re-sends only those to the same comment', async () => {
    let failBad = true;
    const upload = vi.fn().mockImplementation(async (_i: string, f: File) => {
      if (f.name === 'bad.txt' && failBad) throw new Error('x');
      return {};
    });
    const { wrapper } = setup(upload);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    let posted: Awaited<ReturnType<typeof result.current.add>>;
    await act(async () => {
      posted = await result.current.add('', undefined, [file('ok.txt'), file('bad.txt')]);
    });
    expect(posted!.commentId).toBe('new1');
    expect(posted!.failed.map((f) => f.name)).toEqual(['bad.txt']);
    expect(upload).toHaveBeenCalledWith('idea-1', expect.any(File), 'new1');
    upload.mockClear();
    failBad = false;
    let left: File[] = [];
    await act(async () => {
      left = await result.current.retryUploads('new1', posted!.failed);
    });
    expect(left).toEqual([]);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][1].name).toBe('bad.txt');
    expect(upload.mock.calls[0][2]).toBe('new1');
  });
});

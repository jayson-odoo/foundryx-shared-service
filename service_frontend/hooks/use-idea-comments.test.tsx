/**
 * Plan 19 (AC-19-21/22/25): `useIdeaComments(ideaId)` loads via the runtime's
 * `service.listComments`, groups the flat oldest-first list into threads
 * (`{ root, replies }`), and mutates through `addComment` / `editComment` /
 * `deleteComment`, reloading after each. The hook is the only data seam.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IdeaComment } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { useIdeaComments } from './use-idea-comments';

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast: toastMock }));

const c = (over: Partial<IdeaComment>): IdeaComment => ({
  id: 'c1',
  ideaId: 'idea-1',
  parentId: null,
  authorName: 'Alice',
  authorKind: 'user',
  body: 'b',
  isDeleted: false,
  isMine: false,
  canEdit: false,
  canDelete: false,
  createdAt: '2026-10-01T08:00:00Z',
  editedAt: null,
  ...over,
});

function setup(rows: IdeaComment[]) {
  const service = {
    listComments: vi.fn().mockResolvedValue(rows),
    addComment: vi.fn().mockResolvedValue(c({ id: 'new' })),
    editComment: vi.fn().mockResolvedValue(c({ id: 'c1' })),
    deleteComment: vi.fn().mockResolvedValue(undefined),
  } as unknown as IdeaService;
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <IdeationRuntimeProvider
      runtime={{
        mode: 'operator',
        service,
        paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' },
      }}
    >
      {children}
    </IdeationRuntimeProvider>
  );
  return { service, wrapper };
}

beforeEach(() => vi.clearAllMocks());

describe('useIdeaComments', () => {
  it('loads through service.listComments(ideaId) and exposes loading then data', async () => {
    const { service, wrapper } = setup([c({ id: 'c1' })]);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect((service as unknown as { listComments: ReturnType<typeof vi.fn> }).listComments).toHaveBeenCalledWith('idea-1');
    expect(result.current.threads).toHaveLength(1);
  });

  it('groups the flat list into threads: replies under their top-level parent, oldest first', async () => {
    const { wrapper } = setup([
      c({ id: 'c1', createdAt: '2026-10-01T08:00:00Z' }),
      c({ id: 'c2', createdAt: '2026-10-01T09:00:00Z' }),
      c({ id: 'r1', parentId: 'c1', createdAt: '2026-10-01T10:00:00Z' }),
      c({ id: 'r2', parentId: 'c1', createdAt: '2026-10-01T11:00:00Z' }),
      c({ id: 'r3', parentId: 'c2', createdAt: '2026-10-01T12:00:00Z' }),
    ]);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.threads.map((t) => t.root.id)).toEqual(['c1', 'c2']);
    expect(result.current.threads[0].replies.map((r) => r.id)).toEqual(['r1', 'r2']);
    expect(result.current.threads[1].replies.map((r) => r.id)).toEqual(['r3']);
  });

  it('count excludes deleted placeholders', async () => {
    const { wrapper } = setup([
      c({ id: 'c1', isDeleted: true, body: null, authorName: null }),
      c({ id: 'r1', parentId: 'c1' }),
      c({ id: 'c2' }),
    ]);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.count).toBe(2);
  });

  it('add(body, parentId) calls service.addComment(ideaId, body, parentId) then reloads', async () => {
    const { service, wrapper } = setup([]);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const list = (service as unknown as { listComments: ReturnType<typeof vi.fn> }).listComments;
    const before = list.mock.calls.length;
    await act(async () => {
      await result.current.add('hello', 'c1');
    });
    expect((service as unknown as { addComment: ReturnType<typeof vi.fn> }).addComment).toHaveBeenCalledWith('idea-1', 'hello', 'c1');
    expect(list.mock.calls.length).toBeGreaterThan(before);
  });

  it('edit(id, body) and remove(id) call the service and reload', async () => {
    const { service, wrapper } = setup([c({ id: 'c1' })]);
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.edit('c1', 'new body');
    });
    expect((service as unknown as { editComment: ReturnType<typeof vi.fn> }).editComment).toHaveBeenCalledWith('idea-1', 'c1', 'new body');
    await act(async () => {
      await result.current.remove('c1');
    });
    expect((service as unknown as { deleteComment: ReturnType<typeof vi.fn> }).deleteComment).toHaveBeenCalledWith('idea-1', 'c1');
  });

  it('a failed list sets error and no threads', async () => {
    const { service, wrapper } = setup([]);
    (service as unknown as { listComments: ReturnType<typeof vi.fn> }).listComments.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeTruthy();
    expect(result.current.threads).toEqual([]);
  });

  it('a failed add surfaces an error toast (not a thrown render error)', async () => {
    const { service, wrapper } = setup([]);
    (service as unknown as { addComment: ReturnType<typeof vi.fn> }).addComment.mockRejectedValue(new Error('This idea was merged into IDEA-0001.'));
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.add('x');
    });
    expect(toastMock.error).toHaveBeenCalledWith('This idea was merged into IDEA-0001.');
  });

  it('a service without comment support (optional methods) degrades to empty, no crash', async () => {
    const service = {} as IdeaService;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <IdeationRuntimeProvider
        runtime={{
          mode: 'operator',
          service,
          paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' },
        }}
      >
        {children}
      </IdeationRuntimeProvider>
    );
    const { result } = renderHook(() => useIdeaComments('idea-1'), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.threads).toEqual([]);
  });
});

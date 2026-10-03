/**
 * Plan 19 section F (AC-19-33): `usePublicIdeaComments(token)` - thread data for the
 * public status page via `publicIdeaStatusService` (no auth, the token is the
 * capability). Same thread grouping as the operator hook; a 429 on post shows
 * the toast `Too many comments. Try again later.` and does not throw.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IdeaComment } from '@/types/ideation';
import { ApiError } from '@/lib/api-client';

const svc = vi.hoisted(() => ({ listComments: vi.fn(), addComment: vi.fn() }));
vi.mock('@/services/public-idea-status-service', () => ({
  publicIdeaStatusService: { resolve: vi.fn(), ...svc },
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast: toastMock }));

import { usePublicIdeaComments } from './use-public-idea-comments';

const c = (over: Partial<IdeaComment>): IdeaComment => ({
  id: 'c1',
  ideaId: 'idea-1',
  parentId: null,
  authorName: 'Alice',
  authorKind: 'public',
  body: 'b',
  isDeleted: false,
  isMine: false,
  canEdit: false,
  canDelete: false,
  createdAt: '2026-10-01T08:00:00Z',
  editedAt: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  svc.listComments.mockResolvedValue([c({ id: 'c1' }), c({ id: 'r1', parentId: 'c1' })]);
  svc.addComment.mockResolvedValue(c({ id: 'new' }));
});

describe('usePublicIdeaComments', () => {
  it('lists by token and groups into threads', async () => {
    const { result } = renderHook(() => usePublicIdeaComments('tok_abc123def456'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(svc.listComments).toHaveBeenCalledWith('tok_abc123def456');
    expect(result.current.threads).toHaveLength(1);
    expect(result.current.threads[0].replies.map((r) => r.id)).toEqual(['r1']);
    expect(result.current.count).toBe(2);
  });

  it('add(body, parentId) posts via the service by token then reloads', async () => {
    const { result } = renderHook(() => usePublicIdeaComments('tok_abc123def456'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const before = svc.listComments.mock.calls.length;
    await act(async () => {
      await result.current.add('hi', 'c1');
    });
    expect(svc.addComment).toHaveBeenCalledWith('tok_abc123def456', 'hi', 'c1');
    expect(svc.listComments.mock.calls.length).toBeGreaterThan(before);
  });

  it('a 429 shows "Too many comments. Try again later." and does not throw', async () => {
    svc.addComment.mockRejectedValueOnce(new ApiError('Too many requests', 429, 120, undefined));
    const { result } = renderHook(() => usePublicIdeaComments('tok_abc123def456'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.add('spam');
    });
    expect(toastMock.error).toHaveBeenCalledWith('Too many comments. Try again later.');
  });

  it('a non-429 failure shows its message, not the throttle copy', async () => {
    svc.addComment.mockRejectedValueOnce(new ApiError('Body is too long.', 422, null, undefined));
    const { result } = renderHook(() => usePublicIdeaComments('tok_abc123def456'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.add('x');
    });
    expect(toastMock.error).toHaveBeenCalledWith('Body is too long.');
    expect(toastMock.error).not.toHaveBeenCalledWith('Too many comments. Try again later.');
  });
});

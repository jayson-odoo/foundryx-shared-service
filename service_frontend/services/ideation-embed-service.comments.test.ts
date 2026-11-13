/**
 * Plan 19 (AC-19-25): the embed service implements the comment methods against the
 * `/embed/ideas/<id>/comments` routes (embed token, no operator prefix), and
 * votes upvote-only.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

import { ideationEmbedService as svc } from './ideation-embed-service';

beforeEach(() => apiFetch.mockReset());

describe('ideationEmbedService - comments (AC-19-25)', () => {
  it('listComments GETs /embed/ideas/<id>/comments', async () => {
    apiFetch.mockResolvedValue([]);
    await svc.listComments!('a/b');
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/a%2Fb/comments');
  });

  it('addComment POSTs {body, parentId}', async () => {
    apiFetch.mockResolvedValue({ id: 'c2' });
    await svc.addComment!('idea-1', 'hi', 'c1');
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/idea-1/comments', {
      method: 'POST',
      body: JSON.stringify({ body: 'hi', parentId: 'c1' }),
    });
  });

  it('editComment PATCHes and deleteComment DELETEs the embed comment route', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await svc.editComment!('idea-1', 'c1', 'edited');
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/idea-1/comments/c1', {
      method: 'PATCH',
      body: JSON.stringify({ body: 'edited' }),
    });
    apiFetch.mockResolvedValue(undefined);
    await svc.deleteComment!('idea-1', 'c1');
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/idea-1/comments/c1', { method: 'DELETE' });
  });

  it('vote POSTs {dir: "up"} to the embed vote route', async () => {
    apiFetch.mockResolvedValue({ id: 'idea-1' });
    await svc.vote('idea-1', 'up');
    const [url, init] = apiFetch.mock.calls[0] as [string, { body: string }];
    expect(url).toContain('/embed/ideas/idea-1/vote');
    expect(JSON.parse(init.body)).toEqual({ dir: 'up' });
  });
});

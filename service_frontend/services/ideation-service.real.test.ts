import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import type { IdeaCreateInput } from './ideation-service';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

// Imported AFTER the mock is registered.
import { realIdeationService as svc } from './ideation-service.real';

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 3,
  downvotes: 0,
  myVote: null,
  priority: 1,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

beforeEach(() => apiFetch.mockReset());

describe('realIdeationService', () => {
  it('listProducts reads the core catalog and coerces kind, domain-base undefined', async () => {
    apiFetch.mockResolvedValue({
      items: [
        { id: 'p1', name: 'Sorento CRM', kind: 'software' },
        { id: 'p2', name: 'Pallets', kind: 'goods' },
        { id: 'p3', name: 'Consulting', kind: 'service' },
      ],
      total: 3,
      page: 0,
      pageSize: 200,
    });
    const products = await svc.listProducts();
    expect(apiFetch).toHaveBeenCalledWith('/products?page_size=200');
    expect(products).toEqual([
      { id: 'p1', name: 'Sorento CRM', kind: 'software', productDomainBase: null },
      { id: 'p2', name: 'Pallets', kind: 'goods', productDomainBase: null },
      { id: 'p3', name: 'Consulting', kind: 'goods', productDomainBase: null },
    ]);
  });

  it('listIdeas returns the bare array from GET /ideation/ideas', async () => {
    const rows = [anIdea(), anIdea({ id: 'idea-2' })];
    apiFetch.mockResolvedValue(rows);
    await expect(svc.listIdeas()).resolves.toEqual(rows);
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas');
  });

  it('listIdeas({ includeTest: true }) appends the includeTest query param (issue #1179)', async () => {
    apiFetch.mockResolvedValue([]);
    await svc.listIdeas({ includeTest: true });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas?includeTest=true');
  });

  it('listIdeas({ includeTest: false }) omits the query param', async () => {
    apiFetch.mockResolvedValue([]);
    await svc.listIdeas({ includeTest: false });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas');
  });

  it('getIdea encodes the id', async () => {
    apiFetch.mockResolvedValue(anIdea({ id: 'a/b' }));
    await svc.getIdea('a/b');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/a%2Fb');
  });

  // AC-94-53 (issue #94, ideation round 2, backend S2 `f87e320d`): `StatusIn`
  // takes EXACTLY ONE of `status` (the legacy key) or `toStatusId` (the
  // status-engine target id) - REWRITTEN (not deleted, per the house
  // convention for a superseded pinned test) from "POSTs the lifecycle key"
  // now that `setStatus` always carries an engine target id.
  it('setStatus POSTs the target status id', async () => {
    apiFetch.mockResolvedValue(anIdea({ status: 'triaged' }));
    const out = await svc.setStatus('idea-1', 'idea-status-triaged');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/status', {
      method: 'POST',
      body: JSON.stringify({ toStatusId: 'idea-status-triaged' }),
    });
    expect(out.status).toBe('triaged');
  });

  it('vote POSTs the direction', async () => {
    apiFetch.mockResolvedValue(anIdea({ upvotes: 4, myVote: 'up' }));
    await svc.vote('idea-1', 'up');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/vote', {
      method: 'POST',
      body: JSON.stringify({ dir: 'up' }),
    });
  });

  it('vote only ever sends dir "up" (AC-19-12/15)', async () => {
    apiFetch.mockResolvedValue(anIdea({ upvotes: 4, myVote: 'up' }));
    await svc.vote('idea-1', 'up');
    const body = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({ dir: 'up' });
  });

  // ── Plan 19 (AC-19-25) - comments ────────────────────────────────────────────
  it('listComments GETs /ideation/ideas/<id>/comments (encoded) and returns the array', async () => {
    const rows = [{ id: 'c1', ideaId: 'a/b', body: 'x' }];
    apiFetch.mockResolvedValue(rows);
    await expect(svc.listComments!('a/b')).resolves.toEqual(rows);
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/a%2Fb/comments');
  });

  it('addComment POSTs {body, parentId} to the comments collection', async () => {
    apiFetch.mockResolvedValue({ id: 'c2' });
    await svc.addComment!('idea-1', 'hello', 'c1');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/comments', {
      method: 'POST',
      body: JSON.stringify({ body: 'hello', parentId: 'c1' }),
    });
  });

  it('addComment without a parent sends no parentId key', async () => {
    apiFetch.mockResolvedValue({ id: 'c2' });
    await svc.addComment!('idea-1', 'hello');
    const sent = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body);
    expect(sent).toEqual({ body: 'hello' });
  });

  it('editComment PATCHes {body} to the comment', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await svc.editComment!('idea-1', 'c1', 'edited');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/comments/c1', {
      method: 'PATCH',
      body: JSON.stringify({ body: 'edited' }),
    });
  });

  it('deleteComment DELETEs the comment and resolves void', async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(svc.deleteComment!('idea-1', 'c1')).resolves.toBeUndefined();
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/comments/c1', { method: 'DELETE' });
  });

  it('reorderPriority PUTs the ordered ids', async () => {
    apiFetch.mockResolvedValue([anIdea()]);
    await svc.reorderPriority(['idea-2', 'idea-1']);
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/reorder', {
      method: 'PUT',
      body: JSON.stringify({ orderedIds: ['idea-2', 'idea-1'] }),
    });
  });

  it('remove DELETEs and resolves void', async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(svc.remove('idea-1')).resolves.toBeUndefined();
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1', { method: 'DELETE' });
  });

  it('propagates a backend error (e.g. illegal status transition 409)', async () => {
    apiFetch.mockImplementationOnce(() => Promise.reject(new Error('Illegal transition.')));
    await expect(svc.setStatus('idea-1', 'delivered')).rejects.toThrow('Illegal transition.');
  });

  it('createIdea POSTs the operator create payload incl. segregated fields (attachments dropped)', async () => {
    apiFetch.mockResolvedValue(anIdea({ status: 'captured', source: 'manual' }));
    const out = await svc.createIdea({
      productId: 'p1',
      problem: 'Export orders',
      proposedSolution: 'Add a button',
      impact: 'Saves time',
      department: 'CS',
      rawText: 'notes',
      attachments: [{ kind: 'file', name: 'x.pdf' }],
    });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas', {
      method: 'POST',
      body: JSON.stringify({
        productId: 'p1',
        problem: 'Export orders',
        proposedSolution: 'Add a button',
        impact: 'Saves time',
        department: 'CS',
        rawText: 'notes',
      }),
    });
    expect(out.status).toBe('captured');
  });

  it('createIdea defaults omitted segregated fields to empty strings', async () => {
    apiFetch.mockResolvedValue(anIdea());
    await svc.createIdea({ productId: 'p1', problem: 'Export orders', rawText: '' });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas', {
      method: 'POST',
      body: JSON.stringify({
        productId: 'p1',
        problem: 'Export orders',
        proposedSolution: '',
        impact: '',
        department: '',
        rawText: '',
      }),
    });
  });

  it('updateIdea PATCHes only the provided fields', async () => {
    apiFetch.mockResolvedValue(anIdea({ problem: 'y' }));
    await svc.updateIdea('idea-1', { problem: 'y', productId: 'p2', impact: 'faster' });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1', {
      method: 'PATCH',
      body: JSON.stringify({ productId: 'p2', problem: 'y', impact: 'faster' }),
    });
  });

  // AC-94-34 (issue #94, ideation round 2): `updateIdea` becomes fields-ONLY -
  // the two tests above this comment used to assert the OLD status-follow-up
  // branch (`updateIdea` calling `setStatus` when its input carried a changed
  // `status`); that branch is deliberately removed (plan section 4.1, D7 - a
  // save never moves status; the form no longer even collects it). REWRITTEN,
  // not deleted, per the house convention for a superseded pinned test.
  //
  // TEST-FIRST: today's `realIdeationService.updateIdea` still special-cases a
  // `status` key on its input and fires a follow-up `POST /{id}/status` when it
  // differs from the persisted value - this fails (2 calls, not 1) until the
  // branch is removed.
  it('updateIdea is fields only - never calls POST /status, even if the input still carries a status-shaped key (AC-94-34)', async () => {
    apiFetch.mockResolvedValue(anIdea({ status: 'captured', problem: 'y' }));
    const legacyPayloadWithStatus = { problem: 'y', status: 'triaged' } as unknown as Partial<IdeaCreateInput>;
    await svc.updateIdea('idea-1', legacyPayloadWithStatus);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1', {
      method: 'PATCH',
      body: JSON.stringify({ problem: 'y' }),
    });
  });
});

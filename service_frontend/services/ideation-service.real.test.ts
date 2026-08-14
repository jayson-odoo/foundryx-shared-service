import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';

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

  it('getIdea encodes the id', async () => {
    apiFetch.mockResolvedValue(anIdea({ id: 'a/b' }));
    await svc.getIdea('a/b');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/a%2Fb');
  });

  it('setStatus POSTs the lifecycle key', async () => {
    apiFetch.mockResolvedValue(anIdea({ status: 'triaged' }));
    const out = await svc.setStatus('idea-1', 'triaged');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1/status', {
      method: 'POST',
      body: JSON.stringify({ status: 'triaged' }),
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

  it('updateIdea skips setStatus when the status is unchanged (no self-transition)', async () => {
    apiFetch.mockResolvedValue(anIdea({ status: 'captured', problem: 'y' }));
    await svc.updateIdea('idea-1', { problem: 'y', status: 'captured' });
    // Only the PATCH - no follow-up POST /status.
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith('/ideation/ideas/idea-1', {
      method: 'PATCH',
      body: JSON.stringify({ problem: 'y' }),
    });
  });

  it('updateIdea applies a changed status via POST /status after the field PATCH', async () => {
    apiFetch
      .mockResolvedValueOnce(anIdea({ status: 'captured', problem: 'y' })) // PATCH result
      .mockResolvedValueOnce(anIdea({ status: 'triaged', problem: 'y' })); // setStatus result
    const out = await svc.updateIdea('idea-1', { problem: 'y', status: 'triaged' });
    expect(apiFetch).toHaveBeenNthCalledWith(1, '/ideation/ideas/idea-1', {
      method: 'PATCH',
      body: JSON.stringify({ problem: 'y' }),
    });
    expect(apiFetch).toHaveBeenNthCalledWith(2, '/ideation/ideas/idea-1/status', {
      method: 'POST',
      body: JSON.stringify({ status: 'triaged' }),
    });
    expect(out.status).toBe('triaged');
  });
});

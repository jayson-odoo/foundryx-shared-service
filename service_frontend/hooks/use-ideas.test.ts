import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea, Product } from '@/types/ideation';

const svc = vi.hoisted(() => ({
  listIdeas: vi.fn(),
  listProducts: vi.fn(),
  createIdea: vi.fn(),
  setStatus: vi.fn(),
  vote: vi.fn(),
  reorderPriority: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('@/services/ideation-service', () => ({ ideationService: svc }));

import { useIdeas } from './use-ideas';

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 1,
  downvotes: 0,
  myVote: null,
  priority: 1,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  ...over,
});
const aProduct = (): Product => ({ id: 'prod-1', name: 'Sorento CRM', kind: 'software', productDomainBase: null });

beforeEach(() => {
  Object.values(svc).forEach((f) => f.mockReset());
  svc.listIdeas.mockResolvedValue([]);
  svc.listProducts.mockResolvedValue([]);
});

describe('useIdeas', () => {
  it('starts in the loading state', () => {
    const { result } = renderHook(() => useIdeas());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('lands on the empty state when there are no ideas', async () => {
    const { result } = renderHook(() => useIdeas());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ideas).toEqual([]);
    expect(result.current.products).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('loads ideas + products (data state)', async () => {
    svc.listIdeas.mockResolvedValue([anIdea(), anIdea({ id: 'idea-2' })]);
    svc.listProducts.mockResolvedValue([aProduct()]);
    const { result } = renderHook(() => useIdeas());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ideas).toHaveLength(2);
    expect(result.current.products).toHaveLength(1);
  });

  it('surfaces an error when the load fails', async () => {
    svc.listIdeas.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useIdeas());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('boom');
    expect(result.current.ideas).toEqual([]);
  });

  it('vote calls the service and reloads', async () => {
    svc.listIdeas.mockResolvedValue([anIdea()]);
    svc.vote.mockResolvedValue(anIdea({ upvotes: 2, myVote: 'up' }));
    const { result } = renderHook(() => useIdeas());
    await waitFor(() => expect(result.current.loading).toBe(false));
    svc.listIdeas.mockClear();
    await act(async () => {
      await result.current.vote('idea-1', 'up');
    });
    expect(svc.vote).toHaveBeenCalledWith('idea-1', 'up');
    expect(svc.listIdeas).toHaveBeenCalledTimes(1); // reloaded
  });

  it('reorderPriority + setStatus + remove call through to the service', async () => {
    svc.listIdeas.mockResolvedValue([anIdea()]);
    svc.reorderPriority.mockResolvedValue([anIdea()]);
    svc.setStatus.mockResolvedValue(anIdea({ status: 'triaged' }));
    svc.remove.mockResolvedValue(undefined);
    const { result } = renderHook(() => useIdeas());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.reorderPriority(['idea-1']);
      await result.current.setStatus('idea-1', 'triaged');
      await result.current.remove('idea-1');
    });
    expect(svc.reorderPriority).toHaveBeenCalledWith(['idea-1']);
    expect(svc.setStatus).toHaveBeenCalledWith('idea-1', 'triaged');
    expect(svc.remove).toHaveBeenCalledWith('idea-1');
  });
});

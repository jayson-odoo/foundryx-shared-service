/**
 * Plan 20 (AC-20-15/22): the embed service sends the field-level merge map to
 * `/embed/ideas/merge`, reads Similar ideas from `/embed/ideas/<id>/similar`,
 * and sends the card fields on create/update.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

import { ideationEmbedService as svc } from './ideation-embed-service';

beforeEach(() => apiFetch.mockReset());

describe('ideationEmbedService - plan 20', () => {
  it('merge posts the fields map', async () => {
    apiFetch.mockResolvedValue({ id: 'a' });
    await svc.merge('a', ['a', 'b'], { title: ['b'], useCases: ['a', 'b'] });
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/merge', {
      method: 'POST',
      body: JSON.stringify({ survivorId: 'a', ideaIds: ['a', 'b'], fields: { title: ['b'], useCases: ['a', 'b'] } }),
    });
  });

  it('similar GETs the embed route', async () => {
    apiFetch.mockResolvedValue({ available: true, ideas: [] });
    await svc.similar('idea-1');
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/idea-1/similar');
  });

  it('updateIdea sends the card fields and never the product', async () => {
    apiFetch.mockResolvedValue({ id: 'a' });
    await svc.updateIdea('idea-1', { productId: 'p2', currentWorkaround: 'Call sales', useCases: [] });
    expect(apiFetch).toHaveBeenCalledWith('/embed/ideas/idea-1', {
      method: 'PATCH',
      body: JSON.stringify({ useCases: [], currentWorkaround: 'Call sales' }),
    });
  });
});

/**
 * The ideation MOCK service (issue #94, ideation round 2, plan section 3.5) -
 * `ideation-service.ts:57` has named this file for a while ("Mock retained in
 * *.mock.ts for tests") but it has never existed. Slice S1 creates it and
 * extends `IdeaService` with `merge` / `unmerge` / `listMerged` - tested here
 * through the PUBLIC interface only (never internals), so this suite still
 * holds once the real backend replaces the mock behind the one-line swap.
 *
 * TEST-FIRST (PRINCIPLES.md): `./ideation-service.mock` doesn't exist yet -
 * every test below fails with a module-not-found error until S1 lands.
 */
import { describe, expect, it } from 'vitest';
import { mockIdeationService } from './ideation-service.mock';

describe('mockIdeationService - merge and unmerge (AC-94-01/06/07/08)', () => {
  it('merge collapses the group onto the survivor and hides children from listIdeas', async () => {
    const [product] = await mockIdeationService.listProducts();
    const a = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea A', rawText: '' });
    const b = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea B', rawText: '' });

    const survivor = await mockIdeationService.merge(a.id, [a.id, b.id]);
    expect(survivor.id).toBe(a.id);
    expect(survivor.mergedCount).toBe(1);

    const listed = await mockIdeationService.listIdeas();
    expect(listed.map((i) => i.id)).toContain(a.id);
    expect(listed.map((i) => i.id)).not.toContain(b.id);
  });

  it('listMerged returns exactly the merged children', async () => {
    const [product] = await mockIdeationService.listProducts();
    const a = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea C', rawText: '' });
    const b = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea D', rawText: '' });
    await mockIdeationService.merge(a.id, [a.id, b.id]);

    const children = await mockIdeationService.listMerged(a.id);
    expect(children.map((c) => c.id)).toEqual([b.id]);
  });

  it('unmerge restores the child to the list with mergedIntoId cleared', async () => {
    const [product] = await mockIdeationService.listProducts();
    const a = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea E', rawText: '' });
    const b = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea F', rawText: '' });
    await mockIdeationService.merge(a.id, [a.id, b.id]);

    const restored = await mockIdeationService.unmerge(b.id);
    expect(restored.map((r) => r.id)).toEqual([b.id]);
    expect(restored[0].mergedIntoId ?? null).toBeNull();

    const listed = await mockIdeationService.listIdeas();
    expect(listed.map((i) => i.id)).toContain(b.id);
  });

  it('refuses fewer than 2 ideas', async () => {
    const [product] = await mockIdeationService.listProducts();
    const a = await mockIdeationService.createIdea({ productId: product.id, problem: 'Idea G', rawText: '' });
    await expect(mockIdeationService.merge(a.id, [a.id])).rejects.toBeTruthy();
  });
});

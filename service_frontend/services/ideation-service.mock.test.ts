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


describe('mockIdeationService - comments and upvote-only (plan 19, AC-19-12/25)', () => {
  it('addComment then listComments returns it (oldest first); a reply carries its parentId', async () => {
    const [product] = await mockIdeationService.listProducts();
    const idea = await mockIdeationService.createIdea({ productId: product.id, problem: 'Commented idea', rawText: '' });
    const top = await mockIdeationService.addComment!(idea.id, 'first');
    const reply = await mockIdeationService.addComment!(idea.id, 'second', top.id);
    const rows = await mockIdeationService.listComments!(idea.id);
    expect(rows.map((r) => r.body)).toEqual(['first', 'second']);
    expect(reply.parentId).toBe(top.id);
    expect(rows[0].isMine && rows[0].canEdit && rows[0].canDelete).toBe(true);
  });

  it('editComment sets editedAt; deleteComment of a childless comment omits it', async () => {
    const [product] = await mockIdeationService.listProducts();
    const idea = await mockIdeationService.createIdea({ productId: product.id, problem: 'Another', rawText: '' });
    const c = await mockIdeationService.addComment!(idea.id, 'before');
    const edited = await mockIdeationService.editComment!(idea.id, c.id, 'after');
    expect(edited.body).toBe('after');
    expect(edited.editedAt).not.toBeNull();
    await mockIdeationService.deleteComment!(idea.id, c.id);
    expect(await mockIdeationService.listComments!(idea.id)).toEqual([]);
  });

  it('deleting a comment WITH replies leaves a placeholder (isDeleted, null body)', async () => {
    const [product] = await mockIdeationService.listProducts();
    const idea = await mockIdeationService.createIdea({ productId: product.id, problem: 'Third', rawText: '' });
    const top = await mockIdeationService.addComment!(idea.id, 'top');
    await mockIdeationService.addComment!(idea.id, 'reply', top.id);
    await mockIdeationService.deleteComment!(idea.id, top.id);
    const rows = await mockIdeationService.listComments!(idea.id);
    const placeholder = rows.find((r) => r.id === top.id)!;
    expect(placeholder.isDeleted).toBe(true);
    expect(placeholder.body).toBeNull();
  });

  it('vote(id, "up") toggles and the tally never reports downvotes', async () => {
    const [product] = await mockIdeationService.listProducts();
    const idea = await mockIdeationService.createIdea({ productId: product.id, problem: 'Votable', rawText: '' });
    const on = await mockIdeationService.vote(idea.id, 'up');
    expect(on.myVote).toBe('up');
    expect(on.upvotes).toBe(idea.upvotes + 1);
    expect(on.downvotes).toBe(0);
    const off = await mockIdeationService.vote(idea.id, 'up');
    expect(off.myVote).toBeNull();
    expect(off.upvotes).toBe(idea.upvotes);
  });
});

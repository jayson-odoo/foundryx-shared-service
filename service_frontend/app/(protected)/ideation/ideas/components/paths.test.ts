/**
 * AC-94-36 (issue #94, ideation round 2) - `ideaFormHref` gains `{ctx, index,
 * includeTest}` exactly like `brFormHref` (plan section 4.3), so the record
 * pager can carry list context + the "Show test ideas" lane forward.
 *
 * TEST-FIRST (PRINCIPLES.md): `ideaFormHref` only accepts `{edit?}` today -
 * every option below is silently dropped, so this fails until slice S1 lands.
 */
import { describe, expect, it } from 'vitest';
import { ideaFormHref } from './paths';

describe('ideaFormHref - record-nav context (AC-94-36)', () => {
  it('builds a plain path with no options', () => {
    expect(ideaFormHref('idea-1')).toBe('/ideation/ideas/idea-1');
  });

  it('carries ctx + index (i) as query params', () => {
    expect(ideaFormHref('idea-1', { ctx: 'CTX', index: 3 })).toBe(
      '/ideation/ideas/idea-1?ctx=CTX&i=3',
    );
  });

  it('carries includeTest alongside ctx/i, mirroring brFormHref', () => {
    expect(ideaFormHref('idea-1', { ctx: 'CTX', index: 3, includeTest: true })).toBe(
      '/ideation/ideas/idea-1?ctx=CTX&i=3&includeTest=1',
    );
  });

  it('still supports edit mode standalone', () => {
    expect(ideaFormHref('idea-1', { edit: true })).toBe('/ideation/ideas/idea-1?edit=1');
  });
});

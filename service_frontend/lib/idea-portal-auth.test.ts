import { beforeEach, describe, expect, it } from 'vitest';

/** Security review #2: the stored portal token remembers whose it is. */
describe('ideaPortalAuth', () => {
  beforeEach(() => window.localStorage.clear());

  it('persists token + owner and clears both', async () => {
    const { ideaPortalAuth } = await import('./idea-portal-auth');
    ideaPortalAuth.set('t1', 'user-a');
    expect(JSON.parse(window.localStorage.getItem('fx.ideaPortal.session') ?? '{}')).toEqual({ token: 't1', owner: 'user-a' });
    expect(ideaPortalAuth.owner()).toBe('user-a');
    ideaPortalAuth.set(null);
    expect(ideaPortalAuth.get()).toBeNull();
    expect(window.localStorage.getItem('fx.ideaPortal.session')).toBeNull();
  });
});

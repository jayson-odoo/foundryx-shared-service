import { describe, expect, it } from 'vitest';
import staffAuthOptions from '@/app/api/auth/[...nextauth]/auth-options';
import portalAuthOptions from './portal-auth-options';

/**
 * AC-06-18 — machine-checkable proof of session isolation. The portal NextAuth
 * instance MUST use a DISTINCT session-token cookie name from the staff one, so
 * the two sessions can never collide. If these collapse, authenticating one
 * would authenticate the other.
 */
describe('Portal NextAuth session isolation (AC-06-18)', () => {
  it('uses a portal-specific session cookie name', () => {
    const name = portalAuthOptions.cookies?.sessionToken?.name;
    expect(name).toBeDefined();
    expect(name).toMatch(/portal\.session-token$/);
  });

  it('does NOT share the staff session cookie name', () => {
    const portalName = portalAuthOptions.cookies?.sessionToken?.name;
    // Staff uses the NextAuth DEFAULT cookie (no explicit override), which is
    // `next-auth.session-token` / `__Secure-next-auth.session-token`.
    const staffName =
      staffAuthOptions.cookies?.sessionToken?.name ??
      'next-auth.session-token';
    expect(portalName).not.toBe(staffName);
    expect(portalName).not.toMatch(/next-auth\.session-token/);
  });

  it('isolates the csrf and callback-url cookies too', () => {
    expect(portalAuthOptions.cookies?.csrfToken?.name).toMatch(
      /portal\.csrf-token$/,
    );
    expect(portalAuthOptions.cookies?.callbackUrl?.name).toMatch(
      /portal\.callback-url$/,
    );
  });

  it('points its sign-in page at the portal login route', () => {
    expect(portalAuthOptions.pages?.signIn).toBe('/portal/login');
  });

  it('registers a single credentials provider with the portal id', () => {
    expect(portalAuthOptions.providers).toHaveLength(1);
    // The provider id is what signIn('portal-credentials', ...) targets.
    expect(portalAuthOptions.providers[0].id).toBe('portal-credentials');
  });
});

'use client';

import { ReactNode, createContext, useContext } from 'react';
import { usePathname } from 'next/navigation';
import type { PublicBranding } from '@/types/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { AuthFooter } from '@/components/auth/auth-footer';
import { BrandMark } from '@/components/platform/branding';

export interface PublicBrandedShellProps {
  children: ReactNode;
  /** Server-resolved branding (layout) - first paint, no Foundryx flash. */
  initialBranding?: PublicBranding | null;
}

/**
 * Review fix S2 (issue #90): the shell already resolves `isResolved ? live :
 * (initialBranding ?? live)` for its OWN header, so a branded host never
 * flashes the Foundryx mark THERE. A chromeless child (the public idea page,
 * the webchat panel) renders its OWN header/footer and previously called
 * `useTenantBranding()` independently - missing the shell's SSR seed
 * entirely, so a branded host's footer flashed Foundryx until the client
 * fetch resolved. This context carries the shell's ALREADY-resolved value
 * down so a chromeless child never re-derives (and re-flashes) it.
 */
const PublicPageBrandingContext = createContext<PublicBranding | null>(null);

/** The shell's SSR-seeded, already-resolved branding - null outside the shell
 * (a caller falls back to its own `useTenantBranding()` resolution). */
export function usePublicPageBranding(): PublicBranding | null {
  return useContext(PublicPageBrandingContext);
}

/** A path that supplies its OWN chrome (header/footer), never this shell's
 *  header bar + nav-stub `AuthFooter` (Terms/Plans/Contact Us, all `href="#"`):
 *  - the web chat PANEL (D-A7B-25) - a full-bleed surface with no tenant
 *    subdomain context of its own, brand tokens from the SESSION response;
 *    stub links have no place inside an embedded iframe (AC-WEB-47).
 *  - the public idea-status page (issue #90 W1) - a real branded header +
 *    footer BrandMark of its own; a visitor opening a WhatsApp link should
 *    never see instructional stub links either.
 *  - the idea portal (lane IDEA-PORTAL) - its own brand header + tabs.
 *  - the hosted Lead Capture wizard - the session's tenant brand. */
function ownsChromePath(pathname: string | null): boolean {
  return Boolean(
    pathname?.startsWith('/public/webchat/') ||
      pathname?.startsWith('/public/feedback/') ||
      pathname?.startsWith('/portal/feedback') ||
      // The hosted Lead Capture wizard: its tenant comes from the session, not
      // the host, so it draws the tenant's own brand (AC-64-11).
      pathname?.startsWith('/public/lead-capture/'),
  );
}

/**
 * Branded shell for pre-auth PUBLIC surfaces (slice 2 public form fill). A
 * single full-width column - a top brand bar, the page body centered, footer
 * pinned bottom - vs the auth split-screen (forms here can be long). White-label
 * rule (sprint-2/03): a branded tenant shows its logo on a primary chip (or its
 * NAME when it has no logo); an unbranded host shows the Foundryx wordmark.
 */
export function PublicBrandedShell({ children, initialBranding }: PublicBrandedShellProps) {
  const { branding: live, isResolved } = useTenantBranding();
  const branding = isResolved ? live : (initialBranding ?? live);
  const pathname = usePathname();

  if (ownsChromePath(pathname)) {
    return (
      <PublicPageBrandingContext.Provider value={branding}>
        {/* min-w-0: <body> is a flex row; without it a long unbreakable line (a
            one-line URL) widens the whole page past a 375 px screen. */}
        <div className="flex h-full min-h-full min-w-0 grow flex-col">{children}</div>
      </PublicPageBrandingContext.Provider>
    );
  }

  return (
    <PublicPageBrandingContext.Provider value={branding}>
      <div className="flex min-h-full min-w-0 grow flex-col">
        <header className="border-b border-border">
          <div className="mx-auto flex w-full max-w-3xl items-center px-4 py-4 sm:px-6">
            <BrandMark branding={branding} />
          </div>
        </header>
        <main className="flex grow flex-col px-4 py-6 sm:px-6">{children}</main>
        <AuthFooter className="py-8" />
      </div>
    </PublicPageBrandingContext.Provider>
  );
}

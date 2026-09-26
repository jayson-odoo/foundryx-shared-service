'use client';

import { ReactNode } from 'react';
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

/** A path that supplies its OWN chrome (header/footer), never this shell's
 *  header bar + nav-stub `AuthFooter` (Terms/Plans/Contact Us, all `href="#"`):
 *  - the web chat PANEL (D-A7B-25) - a full-bleed surface with no tenant
 *    subdomain context of its own, brand tokens from the SESSION response;
 *    stub links have no place inside an embedded iframe (AC-WEB-47).
 *  - the public idea-status page (issue #90 W1) - a real branded header +
 *    footer BrandMark of its own; a visitor opening a WhatsApp link should
 *    never see instructional stub links either. */
function ownsChromePath(pathname: string | null): boolean {
  return Boolean(
    pathname?.startsWith('/public/webchat/') || pathname?.startsWith('/public/ideas/'),
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
    return <div className="flex h-full min-h-full grow flex-col">{children}</div>;
  }

  return (
    <div className="flex min-h-full grow flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-3xl items-center px-4 py-4 sm:px-6">
          <BrandMark branding={branding} />
        </div>
      </header>
      <main className="flex grow flex-col px-4 py-6 sm:px-6">{children}</main>
      <AuthFooter className="py-8" />
    </div>
  );
}

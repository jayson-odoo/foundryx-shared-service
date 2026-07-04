'use client';

import { ReactNode } from 'react';
import type { PublicBranding } from '@/types/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { AuthBrandPanel } from '@/components/auth/auth-brand-panel';
import { AuthFooter } from '@/components/auth/auth-footer';

export interface BrandedLayoutProps {
  children: ReactNode;
  /** Server-resolved branding (auth layout) — first paint, no FoundryX flash. */
  initialBranding?: PublicBranding | null;
}

/**
 * Branded split-screen auth layout.
 * Left: solid-primary brand panel (hidden < lg). Right: form, footer pinned bottom.
 * Tenant branding (sprint-2/03): the host's logo/slogan/illustration replace the
 * FoundryX defaults; panel color follows the tenant's `--foundryx-primary` override.
 * Branded tenant without a logo shows its NAME (never the FoundryX wordmark —
 * white-label rule); without slogan/illustration = clean panel.
 */
export function BrandedLayout({
  children,
  initialBranding,
}: BrandedLayoutProps) {
  const { branding: live, isResolved } = useTenantBranding();
  // Until the client store resolves, trust the server-rendered value.
  const branding = isResolved ? live : (initialBranding ?? live);

  return (
    <div className="grid grow lg:grid-cols-2">
      {branding.isBranded ? (
        <AuthBrandPanel
          logoSrc={branding.logoUrl}
          brandName={branding.tenantName}
          tagline={branding.slogan}
          illustrationSrc={branding.illustrationUrl}
        />
      ) : (
        <AuthBrandPanel />
      )}

      <div className="flex flex-col p-6 sm:p-8 lg:p-10">
        <div className="flex grow items-center justify-center">
          <div className="w-full max-w-[420px]">{children}</div>
        </div>
        <AuthFooter className="pt-8" />
      </div>
    </div>
  );
}

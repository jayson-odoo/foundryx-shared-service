'use client';

import { ReactNode } from 'react';
import { useTenantBranding } from '@/hooks/use-branding';
import { AuthBrandPanel } from '@/components/auth/auth-brand-panel';
import { AuthFooter } from '@/components/auth/auth-footer';

/**
 * Portal auth shell — the split-screen frame for the portal login / OTP /
 * reset / change-password pages. Mirrors the staff BrandedLayout (white-label:
 * a branded tenant shows its logo/name, never the Dreamz wordmark) but lives
 * inside the `(portal)` tree. Responsive: the brand panel hides < lg and the
 * form takes the full width on mobile.
 */
export function PortalAuthShell({ children }: { children: ReactNode }) {
  const { branding } = useTenantBranding();

  return (
    <div className="grid min-h-screen grow lg:grid-cols-2">
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

'use client';

import { ReactNode, useState } from 'react';
import Image from 'next/image';
import type { PublicBranding } from '@/types/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { AuthFooter } from '@/components/auth/auth-footer';

export interface PublicBrandedShellProps {
  children: ReactNode;
  /** Server-resolved branding (layout) - first paint, no Foundryx flash. */
  initialBranding?: PublicBranding | null;
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

function BrandMark({ branding }: { branding: PublicBranding }) {
  // A logo URL can fail (a DB branding row outliving its blob - see the asset
  // route's 404 guard). White-label rule: a branded tenant NEVER shows a broken
  // image - fall back to its NAME (or the Foundryx mark only when unbranded).
  const [logoFailed, setLogoFailed] = useState(false);
  const nameMark = (
    <span className="font-heading text-lg font-semibold text-foreground">{branding.tenantName}</span>
  );

  if (branding.isBranded && branding.logoUrl && !logoFailed) {
    return (
      <span className="inline-flex items-center rounded-lg bg-primary px-3 py-2">
        <Image
          src={branding.logoUrl}
          alt={branding.tenantName ?? 'Logo'}
          width={120}
          height={32}
          className="h-7 w-auto object-contain"
          unoptimized
          onError={() => setLogoFailed(true)}
        />
      </span>
    );
  }
  if (branding.isBranded && branding.tenantName) {
    return nameMark;
  }
  return (
    <Image
      src="/media/foundryx/foundryx-logo.png"
      alt="Foundryx"
      width={120}
      height={32}
      className="h-7 w-auto object-contain"
      unoptimized
    />
  );
}

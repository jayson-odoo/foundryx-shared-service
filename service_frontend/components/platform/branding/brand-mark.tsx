'use client';

/**
 * Extracted from `app/(public)/public-branded-shell.tsx` (issue #90 W1) - ONE
 * white-label mark, THREE consumers: the shell's header, the public idea
 * page's header/footer. White-label rule (sprint-2/03): a branded tenant
 * shows its logo on a primary chip (or its NAME when it has no logo); an
 * unbranded host shows the Foundryx wordmark. A logo URL can fail (a DB
 * branding row outliving its blob - see the asset route's 404 guard) - a
 * branded tenant NEVER shows a broken image, it falls back to its name.
 */
import { useState } from 'react';
import Image from 'next/image';
import type { PublicBranding } from '@/types/branding';

export function BrandMark({ branding }: { branding: PublicBranding }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const nameMark = (
    <span className="font-heading text-lg font-semibold text-foreground">
      {branding.tenantName}
    </span>
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

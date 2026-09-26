'use client';

/**
 * Extracted from `app/(public)/public-branded-shell.tsx` (issue #90 W1) - ONE
 * white-label mark, TWO consumers: the shell's header (every pre-auth
 * surface) and the public idea page's footer (`PublicIdeaFooter`). White-label
 * rule (sprint-2/03): a branded tenant shows its logo on a primary chip (or
 * its NAME when it has no logo); an unbranded host shows the Foundryx
 * wordmark. A logo URL can fail (a DB branding row outliving its blob - see
 * the asset route's 404 guard) - a branded tenant NEVER shows a broken image,
 * it falls back to its name.
 *
 * The UNBRANDED wordmark (`FoundryxWordmark`) is drawn as inline SVG text -
 * NOT a `next/image` pointed at a file (`/media/foundryx/foundryx-logo.png`
 * was never committed to the repo; it 404s in every environment, showing a
 * broken-image icon to every WhatsApp visitor who opens a public idea link).
 * Inline markup makes no network request, so there is no load to fail and
 * therefore no `onError` fallback to wire - the fix as a category eliminates
 * the failure mode the branded branch's `onError` only degrades gracefully
 * from. Brand color via the `text-primary` token (CSS var, never a raw hex),
 * type via `font-heading` (Poppins).
 */
import { useState } from 'react';
import Image from 'next/image';
import type { PublicBranding } from '@/types/branding';

function FoundryxWordmark() {
  return (
    <svg role="img" aria-label="Foundryx" viewBox="0 0 132 28" className="h-7 w-auto text-primary">
      <text
        x="0"
        y="21"
        fontSize="22"
        fontWeight={600}
        fill="currentColor"
        className="font-heading"
      >
        Foundryx
      </text>
    </svg>
  );
}

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
  return <FoundryxWordmark />;
}

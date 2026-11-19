'use client';

/**
 * The app shell's own logo: the side panel (both looks), the phone top bar and
 * the auth-gate loader. The shells used to point at `/media/app/*.svg`,
 * template files that were never committed to this repo, so they 404 in every
 * environment and every page showed a broken image where the logo belongs.
 *
 * Same white-label rule as `BrandMark` (sprint-2/03): a branded tenant shows
 * its own logo, or its NAME (initial in the square `mini` slot) when it has
 * none or the image fails to load; an unbranded host shows the inline
 * Foundryx wordmark (initial in the `mini` slot). The fallbacks are inline
 * markup, so there is no file left to 404.
 */
import { useState } from 'react';
import type { PublicBranding } from '@/types/branding';
import { cn } from '@/lib/utils';
import { ClampedText } from '@/components/platform/clamped-text';
import { FoundryxWordmark } from './brand-mark';

export interface AppLogoProps {
  branding: PublicBranding;
  /** `full` = the wide logo / wordmark; `mini` = the square slot (collapsed
   *  side panel, phone top bar, loader). */
  variant?: 'full' | 'mini';
  className?: string;
}

export function AppLogo({ branding, variant = 'full', className }: AppLogoProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const name = branding.isBranded ? branding.tenantName : 'Foundryx';
  const src = branding.isBranded
    ? variant === 'mini'
      ? (branding.faviconUrl ?? branding.logoUrl)
      : branding.logoUrl
    : null;

  if (src && src !== failedSrc) {
    return (
      <img
        src={src}
        alt={name ?? 'Logo'}
        className={cn(
          variant === 'mini'
            ? 'size-[24px] object-contain'
            : 'h-[22px] w-auto max-w-[150px] object-contain',
          className,
        )}
        onError={() => setFailedSrc(src)}
      />
    );
  }

  if (variant === 'mini') {
    const initial = name?.trim().charAt(0).toUpperCase();
    if (!initial) return null;
    return (
      <span
        role="img"
        aria-label={name ?? undefined}
        className={cn(
          'inline-flex size-[24px] shrink-0 items-center justify-center rounded-md bg-primary font-heading text-sm font-semibold text-primary-foreground',
          className,
        )}
      >
        {initial}
      </span>
    );
  }

  if (branding.isBranded) {
    return branding.tenantName ? (
      <ClampedText
        text={branding.tenantName}
        lines={1}
        className={cn(
          'max-w-[150px] font-heading text-base font-semibold text-foreground',
          className,
        )}
      />
    ) : null;
  }

  return <FoundryxWordmark className={cn('h-[22px]', className)} />;
}

import type { CSSProperties } from 'react';
import { deriveTransparent } from '@/lib/branding-tokens';
import type { PortalBrand } from '@/types/idea-portal';

/**
 * A product's look on its feedback board (lane SS-MULTI-PRODUCT-BOARD). The
 * board is one shared-service surface served per product: a product sets ONE
 * colour + a name on the Products screen and the board takes them. Product
 * branding, not host-tenant branding - the host app's own theme is untouched
 * because these variables are set on the board's own wrapper only (inline
 * custom properties, the BrandingProvider's governance-clean mechanism).
 */

const HEX = /^#[0-9a-f]{6}$/i;

function luminance(hex: string): number {
  const ch = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

/** White on the colour when it reads (WCAG large-text 3:1), else near-black. */
function foregroundOn(hex: string): string {
  const contrastWithWhite = 1.05 / (luminance(hex) + 0.05);
  return contrastWithWhite >= 3 ? '#ffffff' : '#0a0a0a';
}

/** Inline style for the board wrapper: the whole primary family from one
 * colour. Shades mix with the theme's own background/foreground so light and
 * dark both stay correct. `undefined` (= default look) without a valid colour. */
export function boardBrandStyle(brand: PortalBrand | null | undefined): CSSProperties | undefined {
  const color = brand?.color?.trim().toLowerCase();
  if (!color || !HEX.test(color)) return undefined;
  return {
    '--primary': color,
    '--primary-foreground': foregroundOn(color),
    '--primary-active': `color-mix(in oklab, ${color} 85%, black)`,
    '--primary-accent': `color-mix(in oklab, ${color} 60%, var(--foreground))`,
    '--primary-soft': `color-mix(in oklab, ${color} 12%, var(--background))`,
    '--primary-transparent': deriveTransparent(color),
  } as CSSProperties;
}

/** Browser-tab title for the board: "<name> feedback", null without a name. */
export function boardBrandTitle(brand: PortalBrand | null | undefined): string | null {
  const name = brand?.name?.trim();
  return name ? `${name} feedback` : null;
}

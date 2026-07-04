/**
 * Tenant branding types (sprint-2/03) — white-label foundation. A tenant owns
 * one branding record: image assets (logo / favicon / illustration), a slogan,
 * and curated theme-token overrides (light + dark) over the Dreamz defaults.
 * No record = pure Dreamz branding.
 */

export type ThemeName = 'light' | 'dark';

/**
 * Per-theme token overrides, keyed by WHITELISTED token key (e.g. "primary",
 * "grey-200" — see `lib/branding-tokens.ts`). Partial on purpose: only the
 * keys a tenant changed are stored; everything else falls through to the
 * Dreamz defaults in `css/dreamz-tokens.css`.
 */
export type TokenOverrides = Record<string, string>;

/** The stored theme document — both edit methods (pickers / JSON upload) write this. */
export interface BrandingTokens {
  light: TokenOverrides;
  dark: TokenOverrides;
}

export type BrandingAssetKind = 'logo' | 'favicon' | 'illustration';

/**
 * Tenant social profiles + email footer text (plan sprint-2/07 D4) — set
 * once, consumed by the template engine's Brand Footer / Social Links blocks
 * (and future legal-footer compliance, BL-074).
 */
export interface BrandingSocials {
  facebook: string | null;
  instagram: string | null;
  x: string | null;
  linkedin: string | null;
  youtube: string | null;
  tiktok: string | null;
  website: string | null;
}

export interface BrandingFooter {
  /** Company display line (e.g. legal name). */
  companyName: string | null;
  /** Postal address line (CAN-SPAM/PDPA home — machinery BL-074). */
  addressLine: string | null;
  tagline: string | null;
}

/** A tenant's own branding record (GET /branding — admin surfaces). */
export interface TenantBranding {
  slogan: string | null;
  /** Tenant-chosen product/system name — "Welcome to {appName}" on sign-in. */
  appName: string | null;
  logoUrl: string | null;
  faviconUrl: string | null;
  illustrationUrl: string | null;
  tokens: BrandingTokens | null;
  /** Null until set — Phase B persists; the UI treats null as all-empty. */
  socials: BrandingSocials | null;
  footer: BrandingFooter | null;
  /** Bumped on every save — busts the theme-CSS / asset URLs. */
  version: number;
}

/** Slogan + tokens + socials/footer travel in the JSON save; assets upload separately. */
export interface UpdateBrandingInput {
  slogan: string | null;
  appName: string | null;
  tokens: BrandingTokens | null;
  socials?: BrandingSocials | null;
  footer?: BrandingFooter | null;
}

/**
 * Public branding for a host slug (GET /public/branding/{slug}) — consumed
 * pre-auth by the sign-in page, tab metadata and the app shell. Unknown slug
 * resolves to Dreamz defaults (`isBranded: false`) — never a 404, so tenant
 * existence can't be enumerated.
 */
export interface PublicBranding {
  /** False = render stock Dreamz branding everywhere. */
  isBranded: boolean;
  /** Tenant display name — drives the browser-tab title when branded. */
  tenantName: string | null;
  /** Tenant-chosen product/system name — "Welcome to {appName}" on sign-in. */
  appName: string | null;
  slogan: string | null;
  logoUrl: string | null;
  faviconUrl: string | null;
  illustrationUrl: string | null;
  tokens: BrandingTokens | null;
  version: number;
}

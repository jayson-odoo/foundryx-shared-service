/**
 * Mock branding service (Phase A). In-memory per-tenant branding with the same
 * validation semantics the real backend will enforce (plan 03): token
 * whitelist + color syntax, asset type/size caps, version bump per mutation.
 *
 * Demo data: the `acme` tenant ships pre-branded (blue theme + slogan) so the
 * consumption surfaces can be previewed at `acme.localhost:3001` without
 * touching the editor first. The `default` tenant starts unbranded.
 */
import type {
  BrandingAssetKind,
  BrandingTokens,
  PublicBranding,
  TenantBranding,
  UpdateBrandingInput,
} from '@/types/branding';
import { hasOverrides, validateTokens } from '@/lib/branding-tokens';
import type { BrandingService } from './branding-service';
import { delay } from './mock-query';

/** Mirrors tenant-admin-service.mock ids — the console tab passes tenant IDs. */
const SLUG_BY_TENANT_ID: Record<string, string> = {
  'tnt-001': 'platform',
  'tnt-002': 'default',
  'tnt-003': 'acme',
  'tnt-004': 'borneo-weddings',
  'tnt-005': 'citrus',
  'tnt-006': 'delta-expo',
  'tnt-007': 'evergreen',
  'tnt-008': 'festiva',
};

const TENANT_NAME_BY_SLUG: Record<string, string> = {
  default: 'Default Tenant',
  acme: 'Acme Events',
  'borneo-weddings': 'Borneo Weddings',
  citrus: 'Citrus Conferences',
  'delta-expo': 'Delta Expo',
  evergreen: 'Evergreen Galas',
  festiva: 'Festiva',
};

interface BrandingRecord extends TenantBranding {
  slug: string;
}

const ACME_TOKENS: BrandingTokens = {
  light: {
    primary: '#1f5eff',
    'primary-active': '#1448d1',
    'primary-accent': '#0d2f8f',
    'primary-soft': '#e9efff',
  },
  dark: {
    primary: '#4d82ff',
    'primary-active': '#6f9aff',
    'primary-accent': '#a4bdff',
    'primary-soft': '#0c1733',
  },
};

const records = new Map<string, BrandingRecord>([
  [
    'acme',
    {
      slug: 'acme',
      slogan: 'Events that scale.',
      appName: 'Acme Events',
      logoUrl: '/media/dreamz/dreamz-logo.png',
      faviconUrl: null,
      illustrationUrl: null,
      tokens: ACME_TOKENS,
      socials: null,
      footer: null,
      version: 1,
    },
  ],
]);

const ASSET_RULES: Record<
  BrandingAssetKind,
  { accept: string[]; maxBytes: number }
> = {
  logo: {
    accept: ['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'],
    maxBytes: 2 * 1024 * 1024,
  },
  illustration: {
    accept: ['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'],
    maxBytes: 2 * 1024 * 1024,
  },
  favicon: {
    accept: [
      'image/png',
      'image/jpeg',
      'image/webp',
      'image/x-icon',
      'image/vnd.microsoft.icon',
    ],
    maxBytes: 512 * 1024,
  },
};

function resolveSlug(tenantId?: string): string {
  if (!tenantId) return 'default'; // own tenant in the mock world
  const slug = SLUG_BY_TENANT_ID[tenantId];
  if (!slug) throw new Error('Tenant not found.');
  return slug;
}

function recordFor(slug: string): BrandingRecord {
  const existing = records.get(slug);
  if (existing) return existing;
  const fresh: BrandingRecord = {
    slug,
    slogan: null,
    appName: null,
    logoUrl: null,
    faviconUrl: null,
    illustrationUrl: null,
    tokens: null,
    socials: null,
    footer: null,
    version: 0, // 0 = never saved → unbranded
  };
  records.set(slug, fresh);
  return fresh;
}

function toBranding(r: BrandingRecord): TenantBranding {
  return {
    slogan: r.slogan,
    appName: r.appName,
    logoUrl: r.logoUrl,
    faviconUrl: r.faviconUrl,
    illustrationUrl: r.illustrationUrl,
    tokens: r.tokens
      ? { light: { ...r.tokens.light }, dark: { ...r.tokens.dark } }
      : null,
    socials: r.socials ? { ...r.socials } : null,
    footer: r.footer ? { ...r.footer } : null,
    version: r.version,
  };
}

function isBranded(r: BrandingRecord): boolean {
  return !!(
    r.logoUrl ||
    r.faviconUrl ||
    r.illustrationUrl ||
    r.slogan ||
    r.appName ||
    hasOverrides(r.tokens)
  );
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('Could not read the file.'));
    reader.readAsDataURL(file);
  });
}

export const mockBrandingService: BrandingService = {
  get(tenantId) {
    return delay(toBranding(recordFor(resolveSlug(tenantId))));
  },

  update(input: UpdateBrandingInput, tenantId) {
    const record = recordFor(resolveSlug(tenantId));
    // Same gate the backend applies — reject anything off-whitelist loudly.
    let tokens: BrandingTokens | null = null;
    if (input.tokens) {
      const validated = validateTokens(input.tokens);
      if (validated.errors.length) {
        return Promise.reject(new Error(validated.errors[0]));
      }
      tokens = validated.tokens;
    }
    record.slogan = input.slogan?.trim() ? input.slogan.trim() : null;
    record.appName = input.appName?.trim() ? input.appName.trim() : null;
    record.tokens = tokens;
    // Social & footer (plan 07 D4) — undefined = caller didn't touch them.
    if (input.socials !== undefined) record.socials = input.socials;
    if (input.footer !== undefined) record.footer = input.footer;
    record.version += 1;
    return delay(toBranding(record));
  },

  async uploadAsset(kind, file, tenantId) {
    const rules = ASSET_RULES[kind];
    if (!rules.accept.includes(file.type)) {
      throw new Error(`Unsupported file type for ${kind}.`);
    }
    if (file.size > rules.maxBytes) {
      throw new Error(
        `File too large — max ${Math.round(rules.maxBytes / 1024)} KB for ${kind}.`,
      );
    }
    const record = recordFor(resolveSlug(tenantId));
    const dataUrl = await readAsDataUrl(file);
    if (kind === 'logo') record.logoUrl = dataUrl;
    else if (kind === 'favicon') record.faviconUrl = dataUrl;
    else record.illustrationUrl = dataUrl;
    record.version += 1;
    return delay(toBranding(record));
  },

  removeAsset(kind, tenantId) {
    const record = recordFor(resolveSlug(tenantId));
    if (kind === 'logo') record.logoUrl = null;
    else if (kind === 'favicon') record.faviconUrl = null;
    else record.illustrationUrl = null;
    record.version += 1;
    return delay(toBranding(record));
  },

  publicBranding(slug) {
    const record = records.get(slug);
    if (!record || !isBranded(record)) {
      // Unknown slug OR unbranded tenant — uniform Dreamz defaults (plan 03:
      // never 404, no tenant enumeration).
      return delay<PublicBranding>(
        {
          isBranded: false,
          tenantName: null,
          appName: null,
          slogan: null,
          logoUrl: null,
          faviconUrl: null,
          illustrationUrl: null,
          tokens: null,
          version: 0,
        },
        120,
      );
    }
    return delay<PublicBranding>(
      {
        isBranded: true,
        tenantName: TENANT_NAME_BY_SLUG[slug] ?? slug,
        appName: record.appName,
        slogan: record.slogan,
        logoUrl: record.logoUrl,
        faviconUrl: record.faviconUrl,
        illustrationUrl: record.illustrationUrl,
        tokens: record.tokens,
        version: record.version,
      },
      120,
    );
  },
};

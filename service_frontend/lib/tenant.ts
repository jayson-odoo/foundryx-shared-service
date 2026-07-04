/**
 * Tenant slug rules + resolution (plan 07 §4, §6).
 *
 * The slug is the tenant's URL identity (subdomain) — lowercase kebab, immutable
 * after creation. `deriveTenantSlug` resolves the current tenant from the
 * hostname (subdomain-based resolution, D4); local dev falls back to
 * NEXT_PUBLIC_TENANT_SLUG, then "default".
 */

/** Slugs that can never be tenant identities (infra/system hostnames). */
export const RESERVED_TENANT_SLUGS: readonly string[] = [
  'www',
  'api',
  'app',
  'admin',
  'platform',
  'default',
  'mail',
  'ftp',
  'assets',
  'static',
  'docs',
  'status',
  'support',
  'billing',
];

/** lowercase kebab, 3–63 chars, no leading/trailing/double hyphen. */
const SLUG_RE = /^[a-z0-9](?:-?[a-z0-9]){2,62}$/;

export function isValidTenantSlug(slug: string): boolean {
  return SLUG_RE.test(slug);
}

export function isReservedTenantSlug(slug: string): boolean {
  return RESERVED_TENANT_SLUGS.includes(slug);
}

/** Hosts that can never carry a tenant subdomain (local dev / raw IPs). */
const NON_TENANT_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0']);

/**
 * Subdomains that are infra aliases, never tenant homes. This is the reserved
 * list MINUS `platform`/`default` — those are real (seeded) tenants and must
 * resolve (the operator console lives at platform.<domain>).
 */
const NON_TENANT_SUBDOMAINS = new Set(
  RESERVED_TENANT_SLUGS.filter((s) => s !== 'platform' && s !== 'default'),
);

const FALLBACK_SLUG = process.env.NEXT_PUBLIC_TENANT_SLUG || 'default';

/**
 * Build a tenant's URL from the host the operator is browsing on —
 * swap the subdomain for the tenant slug, keep domain/port/protocol.
 * platform.localhost:3001 + acme → http://acme.localhost:3001;
 * platform.foundryxems.com + acme → https://acme.foundryxems.com.
 */
export function tenantUrl(slug: string, location: Location): string {
  const [host, port] = location.host.toLowerCase().split(':');
  const labels = host.split('.');
  // Base domain = everything after the current subdomain; bare hosts
  // (localhost, foundryxems.com) are already the base.
  const isSubdomained = labels.length >= 3 || (labels.length === 2 && labels[1] === 'localhost');
  const base = isSubdomained ? labels.slice(1).join('.') : host;
  return `${location.protocol}//${slug}.${base}${port ? `:${port}` : ''}`;
}

/**
 * Resolve the tenant slug from a hostname: first label of a 3+-label host
 * (`acme.foundryxems.com` → `acme`) or of `<slug>.localhost` (dev), unless it's
 * an infra alias (`www`, `api`, …). Bare domains, localhost and IPs fall back
 * to the dev/default slug.
 */
export function deriveTenantSlug(hostname: string): string {
  const host = hostname.toLowerCase().split(':')[0];
  if (NON_TENANT_HOSTS.has(host) || /^\d+(\.\d+){3}$/.test(host)) return FALLBACK_SLUG;

  const labels = host.split('.');
  // `<slug>.localhost` (browsers resolve *.localhost to 127.0.0.1) or a
  // subdomain + domain + tld host (acme.foundryxems.com).
  const isDevSubdomain = labels.length === 2 && labels[1] === 'localhost';
  if (!isDevSubdomain && labels.length < 3) return FALLBACK_SLUG;

  const candidate = labels[0];
  if (NON_TENANT_SUBDOMAINS.has(candidate) || !isValidTenantSlug(candidate)) return FALLBACK_SLUG;
  return candidate;
}

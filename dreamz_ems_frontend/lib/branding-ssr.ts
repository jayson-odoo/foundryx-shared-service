/**
 * Server-side branding resolution (sprint-2/03 Phase B) — the first-paint
 * path. The root layout derives the tenant slug from the request host, pulls
 * the public branding JSON (title/favicon via generateMetadata) and emits the
 * backend-generated theme.css <link>. The client-side BrandingProvider keeps
 * everything fresh after in-session edits.
 */
import { cache } from 'react';
import { headers } from 'next/headers';
import type { PublicBranding } from '@/types/branding';
import { deriveTenantSlug } from '@/lib/tenant';

// Server-side fetch target (NextAuth's BACKEND_API_URL convention) with the
// public var as fallback; the <link> href must use the PUBLIC base — the
// browser fetches it.
const SERVER_API =
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_BACKEND_API_URL ||
  'http://localhost:8001';
const PUBLIC_API =
  process.env.NEXT_PUBLIC_BACKEND_API_URL || 'http://localhost:8001';

export interface RequestBranding {
  slug: string;
  /** null = backend unreachable / non-OK — render Dreamz defaults, never block. */
  branding: PublicBranding | null;
}

/** Per-request memoized (generateMetadata + layout share one fetch). */
export const getRequestBranding = cache(async (): Promise<RequestBranding> => {
  const host = (await headers()).get('host') ?? 'localhost';
  const slug = deriveTenantSlug(host);
  try {
    // Branding changes rarely: a short server-side revalidate amortizes the
    // per-request fetch; the in-session BrandingProvider covers freshness for
    // the editing admin. The 2s abort keeps a degraded backend from stalling
    // first paint app-wide — branding is cosmetic, never worth blocking on.
    const res = await fetch(`${SERVER_API}/public/branding/${slug}`, {
      next: { revalidate: 60 },
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return { slug, branding: null };
    return { slug, branding: (await res.json()) as PublicBranding };
  } catch {
    return { slug, branding: null };
  }
});

/** Browser-facing theme stylesheet URL, version-busted per save. */
export function themeCssHref(slug: string, version: number): string {
  return `${PUBLIC_API}/public/branding/${slug}/theme.css?v=${version}`;
}

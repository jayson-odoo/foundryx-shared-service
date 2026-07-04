import { ReactNode } from 'react';
import { getRequestBranding } from '@/lib/branding-ssr';
import { BrandedLayout } from './layouts/branded';

/**
 * Auth layout (server) — resolves the host's branding ONCE on the server and
 * seeds the client layout with it, so a branded tenant's sign-in page never
 * flashes the Dreamz logo/tagline before the client store resolves
 * (white-label rule; review finding sprint-2/03).
 */
export default async function Layout({ children }: { children: ReactNode }) {
  const { branding } = await getRequestBranding();
  return <BrandedLayout initialBranding={branding}>{children}</BrandedLayout>;
}

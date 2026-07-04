import { ReactNode } from 'react';
import { getRequestBranding } from '@/lib/branding-ssr';
import { PublicBrandedShell } from './public-branded-shell';

/**
 * Public (pre-auth) layout (server) — resolves the host's branding ONCE on the
 * server and seeds the client shell, so a branded tenant's public form page
 * never flashes the FoundryX logo (white-label rule; the (auth) layout precedent).
 * No auth guard: this group is outside (protected).
 */
export default async function PublicLayout({ children }: { children: ReactNode }) {
  const { branding } = await getRequestBranding();
  return <PublicBrandedShell initialBranding={branding}>{children}</PublicBrandedShell>;
}

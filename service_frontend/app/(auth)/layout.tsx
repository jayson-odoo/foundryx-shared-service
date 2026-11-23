import { ReactNode } from 'react';
import { getRequestBranding } from '@/lib/branding-ssr';
import { FxComponentsOff } from '@/components/fx/fx-components-off';
import { BrandedLayout } from './layouts/branded';

/**
 * Auth layout (server) - resolves the host's branding ONCE on the server and
 * seeds the client layout with it, so a branded tenant's sign-in page never
 * flashes the Foundryx logo/tagline before the client store resolves
 * (white-label rule; review finding sprint-2/03).
 */
export default async function Layout({ children }: { children: ReactNode }) {
  const { branding } = await getRequestBranding();
  return (
    <FxComponentsOff>
      <BrandedLayout initialBranding={branding}>{children}</BrandedLayout>
    </FxComponentsOff>
  );
}

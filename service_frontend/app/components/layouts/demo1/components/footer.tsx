'use client';

import { Container } from '@/components/common/container';
import { useTenantBranding } from '@/hooks/use-branding';

/**
 * AC-DLA-71 - the Metronic footer rendered "Keenthemes Inc." and a
 * Docs/Purchase/FAQ/Support/License nav, none of which the product owns.
 * White-label: shows the tenant name when branded, nothing when not (never
 * a hardcoded "Foundryx" in tenant-facing chrome) - no external nav at all,
 * since the product does not publish any of those pages today.
 */
export function Footer() {
  const { branding, isResolved } = useTenantBranding();
  const currentYear = new Date().getFullYear();
  const tenantName = isResolved && branding.isBranded ? branding.tenantName : null;

  return (
    <footer className="footer">
      {/* Fluid to match the header + content pages (plan 06). */}
      <Container width="fluid">
        <div className="flex justify-center items-center py-5">
          {tenantName && (
            <span className="font-normal text-sm text-muted-foreground">
              {currentYear} &copy; {tenantName}
            </span>
          )}
        </div>
      </Container>
    </footer>
  );
}

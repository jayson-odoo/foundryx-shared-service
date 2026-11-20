/**
 * Issue #90 W1 - "a footer with the Foundryx mark" vs white-label (Q2, binding
 * ruling): the SAME `BrandMark` the header uses - the Foundryx wordmark on an
 * unbranded host, the tenant's own mark on a branded one. Never two different
 * white-label rules for one page.
 */
import { BrandMark } from '@/components/platform/branding';
import type { PublicBranding } from '@/types/branding';

export function PublicIdeaFooter({ branding }: { branding: PublicBranding }) {
  return (
    <footer className="mt-auto flex justify-center py-6">
      <BrandMark branding={branding} />
    </footer>
  );
}

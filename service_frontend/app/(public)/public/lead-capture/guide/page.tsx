import type { Metadata } from 'next';
import { getRequestBranding } from '@/lib/branding-ssr';
import { guideApiBase } from '@/lib/lead-capture-guide';
import { LeadCaptureGuide } from './lead-capture-guide';

export const metadata: Metadata = { title: 'Lead Capture guide' };

/**
 * Public Lead Capture guide (lane META-LEADS-GUIDE-PAGE): no login. The
 * partner name + logo are the host tenant's branding (one tenant = one
 * partner app); an unbranded host reads "your app". The API base is resolved
 * here on the server from the backend URL, never typed into the page.
 */
export default async function LeadCaptureGuidePage() {
  const { branding } = await getRequestBranding();
  const branded = branding?.isBranded ? branding : null;
  return (
    <LeadCaptureGuide partnerName={branded?.tenantName ?? null} apiBase={guideApiBase()} branding={branded} />
  );
}

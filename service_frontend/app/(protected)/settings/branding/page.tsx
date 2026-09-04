'use client';

import { useCan } from '@/hooks/use-can';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { BrandingEditor } from '@/components/platform/branding';
import { PageHeader } from '@/components/platform/page-header';

/**
 * Tenant branding hub (sprint-2/03) - logo / favicon / illustration uploads,
 * slogan, and the curated light+dark theme editor. Gated by branding.read;
 * edits additionally need branding.manage.
 */
export default function BrandingPage() {
  const { can } = useCan();

  return (
    <RequirePermission permission="branding.read">
      <Container width="fluid">
        <PageHeader
          description={
            <>
              Your logo, slogan and colors across the sign-in page, browser tab
              and app
            </>
          }
        />
        <BrandingEditor canManage={can('branding.manage')} />
      </Container>
    </RequirePermission>
  );
}

'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useLeadsListConfig } from './components/use-leads-list-config';

function LeadsList() {
  const sourceId = useSearchParams().get('source');
  const config = useLeadsListConfig(sourceId);
  return <ResourceList key={sourceId ?? 'all'} config={config} />;
}

/** Lead Capture > Leads (plan 64 AC-64-53). */
export default function LeadCaptureLeadsPage() {
  return (
    <RequirePermission permission="lead_capture.view">
      <Container width="fluid">
        <Suspense>
          <LeadsList />
        </Suspense>
      </Container>
    </RequirePermission>
  );
}

'use client';

import { useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { useLeadCaptureWizardLauncher } from '@/hooks/use-lead-capture-sources';
import { useSourcesListConfig } from './components/use-sources-list-config';

/** Lead Capture > Sources (plan 64 AC-64-05). */
export default function LeadCaptureSourcesPage() {
  const [version, setVersion] = useState(0);
  const openWizard = useLeadCaptureWizardLauncher(() => setVersion((v) => v + 1));
  const config = useSourcesListConfig(openWizard);
  return (
    <RequirePermission permission="lead_capture.view">
      <Container width="fluid">
        {/* Create sits on the grid's toolbar row (standing rule): the page
            owns the header, the list renders without its own. */}
        <PageHeader title={config.pageTitle} />
        <ResourceList key={version} config={config} hideHeader />
      </Container>
    </RequirePermission>
  );
}

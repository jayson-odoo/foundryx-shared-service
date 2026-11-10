'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useIntegrationLogsListConfig } from './components/use-integration-logs-list-config';

export default function DeveloperLogsPage() {
  const config = useIntegrationLogsListConfig();

  return (
    <RequirePermission permission="integration_logs.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

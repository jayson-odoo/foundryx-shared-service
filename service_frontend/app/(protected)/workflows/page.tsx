'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useWorkflowsListConfig } from './components/use-workflows-list-config';

export default function WorkflowsPage() {
  const config = useWorkflowsListConfig();

  return (
    <RequirePermission permission="workflows.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

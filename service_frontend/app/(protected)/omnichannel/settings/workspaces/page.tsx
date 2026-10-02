'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useWorkspacesListConfig } from './components/use-workspaces-list-config';

export default function WorkspacesPage() {
  const config = useWorkspacesListConfig();

  return (
    <RequirePermission permission="workspaces.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

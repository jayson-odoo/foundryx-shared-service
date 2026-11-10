'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { useBroadcastsListConfig } from './components/use-broadcasts-list-config';

export default function BroadcastsPage() {
  const { workspaceId } = useWorkspaceId();
  const config = useBroadcastsListConfig(workspaceId);

  return (
    <RequirePermission permission="broadcasts.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

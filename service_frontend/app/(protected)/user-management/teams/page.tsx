'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useTeamsListConfig } from './components/use-teams-list-config';

export default function TeamsPage() {
  const config = useTeamsListConfig();

  return (
    <RequirePermission permission="teams.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

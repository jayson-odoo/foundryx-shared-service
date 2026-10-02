'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useRolesListConfig } from './components/use-roles-list-config';

export default function RolesPage() {
  const config = useRolesListConfig();

  return (
    <RequirePermission permission="roles.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

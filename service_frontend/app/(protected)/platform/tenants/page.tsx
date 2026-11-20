'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useTenantsListConfig } from './components/use-tenants-list-config';

export default function TenantsPage() {
  const config = useTenantsListConfig();

  return (
    <RequirePermission permission="tenants.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

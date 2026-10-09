'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useMigrationListConfig } from './components/use-migration-list-config';

/** respond.io migration job history (plan 33 S0, AC-MIG-02). */
export default function MigrationListPage() {
  const config = useMigrationListConfig();

  return (
    <RequirePermission permission="omnichannel_migration.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

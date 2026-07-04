'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { useTenantsListConfig } from './components/use-tenants-list-config';

export default function TenantsPage() {
  const config = useTenantsListConfig();

  return (
    <RequirePermission permission="tenants.read">
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              Manage tenants on this deployment — provision, suspend and archive tenants.
            </ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <ResourceList config={config} />
      </Container>
    </Fragment>
    </RequirePermission>
  );
}

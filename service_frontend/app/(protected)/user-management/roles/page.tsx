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
import { useRolesListConfig } from './components/use-roles-list-config';

export default function RolesPage() {
  const config = useRolesListConfig();

  return (
    <RequirePermission permission="roles.read">
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              Manage roles and the permissions they grant across the system.
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

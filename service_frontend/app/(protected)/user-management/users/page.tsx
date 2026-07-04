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
import { useUsersListConfig } from './components/use-users-list-config';

export default function UsersPage() {
  const config = useUsersListConfig();

  return (
    <RequirePermission permission="users.read">
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>Manage users, their roles and access.</ToolbarDescription>
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

'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useStatusEntitiesListConfig } from '@/components/platform/status-engine';

/**
 * Tenant surface of the Status Engine (sprint-2/01) — entity list; a tenant's
 * first edit forks the entity's whole set into the workspace (D7). Entities
 * arrive as installed modules register them; the tenant lifecycle itself is
 * platform-owned and hidden here.
 */
export default function TenantStatusesPage() {
  const config = useStatusEntitiesListConfig('/settings/statuses');

  return (
    <RequirePermission permission="statuses.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Configure statuses, transition flows, approvals and notifications for your
                workspace.
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

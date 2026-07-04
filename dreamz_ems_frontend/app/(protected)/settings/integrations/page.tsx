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
import { useConnectionsListConfig } from './components/use-connections-list-config';

/**
 * Integrations (plan 09; Resource shell since plan 06 D6) — the tenant's
 * connections to external services (email, storage, …). List + full-page form,
 * like every entity; the card grid + wizard are gone. Gated integrations.read;
 * connect/edit/test/disconnect additionally need integrations.manage.
 */
export default function IntegrationsPage() {
  const config = useConnectionsListConfig();

  return (
    <RequirePermission permission="integrations.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Connect external services — email, storage and more.
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

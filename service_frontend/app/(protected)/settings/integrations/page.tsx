'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useConnectionsListConfig } from './components/use-connections-list-config';

/**
 * Integrations (plan 09; Resource shell since plan 06 D6) - the tenant's
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
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

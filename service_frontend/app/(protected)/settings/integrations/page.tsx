'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useConnectionsListConfig } from './components/use-connections-list-config';
import { FxIntegrationsPage } from './components/fx-integrations-page';
import { useFx } from '@/hooks/use-fx';

/**
 * Integrations (plan 09; Resource shell since plan 06 D6) - the tenant's
 * connections to external services (email, storage, …). List + full-page form,
 * like every entity; the card grid + wizard are gone. Gated integrations.read;
 * connect/edit/test/disconnect additionally need integrations.manage.
 */
export default function IntegrationsPage() {
  // Foundryx UIUX switch: connected services while on; today's list while off.
  return useFx() ? (
    <RequirePermission permission="integrations.read">
      <FxIntegrationsPage />
    </RequirePermission>
  ) : (
    <IntegrationsPageLegacy />
  );
}

function IntegrationsPageLegacy() {
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

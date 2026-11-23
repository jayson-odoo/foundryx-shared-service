'use client';

import { Fragment, useMemo } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useStatusEntitiesListConfig } from '@/components/platform/status-engine';

/**
 * Tenant surface of the Status Engine (sprint-2/01) - entity list; a tenant's
 * first edit forks the entity's whole set into the workspace (D7). Entities
 * arrive as installed modules register them; the tenant lifecycle itself is
 * platform-owned and hidden here.
 */
export default function TenantStatusesPage() {
  const base = useStatusEntitiesListConfig('/settings/statuses');
  // Foundryx UIUX switch only (slice W4-SETTINGS); ignored while off. The
  // shared config is left as it is (the platform Status Engine uses it too).
  const config = useMemo(
    () => ({
      ...base,
      fx: {
        noun: 'entities',
        copyable: ['entity'],
        cardLines: [['entity', 'source'], ['module']],
        phoneHidden: ['statuses', 'transitions'],
      },
    }),
    [base],
  );

  return (
    <RequirePermission permission="statuses.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

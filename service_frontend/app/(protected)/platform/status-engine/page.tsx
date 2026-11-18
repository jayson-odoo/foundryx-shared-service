'use client';

import { Fragment, useMemo } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useStatusEntitiesListConfig } from '@/components/platform/status-engine';

/**
 * Operator surface of the Status Engine (sprint-2/01) - entity LIST (the
 * Resource shell); row click opens the entity's detail form (Flow + Statuses
 * tabs) editing the PLATFORM DEFAULT sets every un-forked tenant inherits.
 */
export default function PlatformStatusEnginePage() {
  const base = useStatusEntitiesListConfig('/platform/status-engine');
  // Foundryx UIUX switch only (slice W3-PLATFORM); ignored while off. The
  // shared config is left as it is (the tenant settings page uses it too).
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

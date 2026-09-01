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
 * Operator surface of the Status Engine (sprint-2/01) - entity LIST (the
 * Resource shell); row click opens the entity's detail form (Flow + Statuses
 * tabs) editing the PLATFORM DEFAULT sets every un-forked tenant inherits.
 */
export default function PlatformStatusEnginePage() {
  const config = useStatusEntitiesListConfig('/platform/status-engine');

  return (
    <RequirePermission permission="statuses.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Platform default statuses and transition flows - tenants inherit these until
                they customize.
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

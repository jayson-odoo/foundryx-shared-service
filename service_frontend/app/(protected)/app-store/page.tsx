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
import { useModuleListConfig } from '@/components/platform/app-store';

/**
 * Tenant App Store (plan 08 §8; migrated onto the Resource shell, sprint-3) —
 * card view by default with a list toggle; install / deactivate / reactivate /
 * update / uninstall via the row + bulk "…" menu, gated by `app_store.*`.
 */
export default function AppStorePage() {
  const config = useModuleListConfig();

  return (
    <RequirePermission permission="app_store.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Install and manage services for this workspace.</ToolbarDescription>
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

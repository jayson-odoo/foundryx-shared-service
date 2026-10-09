'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { useModuleListConfig } from '@/components/platform/app-store';
import { ResourceList } from '@/components/platform/resource-list';

/**
 * Tenant App Store (plan 08 §8; migrated onto the Resource shell, sprint-3) -
 * card view by default with a list toggle; install / deactivate / reactivate /
 * update / uninstall via the row + bulk "…" menu, gated by `app_store.*`.
 */
export default function AppStorePage() {
  const config = useModuleListConfig();

  return (
    <RequirePermission permission="app_store.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

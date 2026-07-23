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
import { AC_SYNC_READ } from '../components/autocount-meta';
import { useAutocountJobsListConfig } from './components/use-jobs-list-config';

/**
 * AutoCount Review (plan 15, AC-15-02) — a Resource list of sync batches
 * awaiting attention. A row opens the batch review surface. Gated
 * `autocount.sync.read`.
 */
export default function AutocountReviewListPage() {
  const config = useAutocountJobsListConfig();

  return (
    <RequirePermission permission={AC_SYNC_READ}>
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="Review" />
              <ToolbarDescription>
                Sync batches awaiting review, approval or already pushed.
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

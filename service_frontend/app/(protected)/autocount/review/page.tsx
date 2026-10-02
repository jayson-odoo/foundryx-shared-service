'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { AC_SYNC_READ } from '../components/autocount-meta';
import { useAutocountJobsListConfig } from './components/use-jobs-list-config';

/**
 * AutoCount Review (plan 15, AC-15-02) - a Resource list of sync batches
 * awaiting attention. A row opens the batch review surface. Gated
 * `autocount.sync.read`.
 */
export default function AutocountReviewListPage() {
  const config = useAutocountJobsListConfig();

  return (
    <RequirePermission permission={AC_SYNC_READ}>
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}

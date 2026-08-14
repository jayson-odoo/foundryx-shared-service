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
import { useJobsListConfig } from './use-jobs-list-config';

/**
 * Jobs (sprint-4/10 AC-10-19) - the generic background-jobs history on the
 * Resource shell. Readable by any authenticated user (jobs are tenant-scoped
 * server-side); the migration controls in the row "…" need
 * `integrations.migrate_storage`.
 */
export default function JobsPage() {
  const config = useJobsListConfig();

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text="Jobs" />
            <ToolbarDescription>Background jobs across your workspace.</ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <ResourceList config={config} />
      </Container>
    </Fragment>
  );
}

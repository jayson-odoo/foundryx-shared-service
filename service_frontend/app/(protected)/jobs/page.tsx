'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { useJobsListConfig } from './use-jobs-list-config';
import { useFx } from '@/hooks/use-fx';

/**
 * Foundryx UIUX switch only: the jobs list's search box searches nothing (the
 * backend list takes no search), so under the new look it is hidden rather
 * than given new behaviour. The list shell has no option for that yet, so the
 * box is hidden from here (finding for the list shell: an `fx.hideSearch`).
 */
const FX_HIDE_LIST_SEARCH = '[&_[data-fx-list]_div:has(>input[aria-label=Search])]:hidden';

/**
 * Jobs (sprint-4/10 AC-10-19) - the generic background-jobs history on the
 * Resource shell. Job reads follow each type's read permission (tenant-scoped
 * server-side); the migration controls in the row "…" need
 * `integrations.migrate_storage`.
 */
export default function JobsPage() {
  const config = useJobsListConfig();
  const fx = useFx();

  if (fx) {
    return (
      <Container width="fluid">
        <div className={FX_HIDE_LIST_SEARCH}>
          <ResourceList config={config} />
        </div>
      </Container>
    );
  }

  return (
    <Fragment>
      <Container width="fluid">
        <ResourceList config={config} />
      </Container>
    </Fragment>
  );
}

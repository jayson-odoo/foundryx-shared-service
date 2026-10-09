'use client';

import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { useAutocountCompanies } from '@/hooks/use-autocount-pull';
import { BuildSnapshotDialog } from './build-snapshot-dialog';
import { IssueKeyDialog } from './issue-key-dialog';
import { useAutocountPullListConfig } from './use-pull-list-config';

/**
 * `/autocount/pull` (AC-10-38) - Keys | Snapshots on the Resource shell.
 * Issue key and Build snapshot are dialogs (never a hand-rolled page), fired
 * from the segment-aware Create button.
 */
export function PullView() {
  const { companies } = useAutocountCompanies();
  const [issueOpen, setIssueOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const config = useAutocountPullListConfig({
    companies,
    onIssueKey: () => setIssueOpen(true),
    onBuildSnapshot: () => setBuildOpen(true),
  });

  return (
    <Container width="fluid">
      <ResourceList key={reloadKey} config={config} />
      <IssueKeyDialog
        open={issueOpen}
        onOpenChange={setIssueOpen}
        companies={companies}
        onIssued={reload}
      />
      <BuildSnapshotDialog
        open={buildOpen}
        onOpenChange={setBuildOpen}
        companies={companies}
        onBuilt={reload}
      />
    </Container>
  );
}

'use client';

import { Fragment, useState } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { refreshTerminology } from '@/hooks/use-terminology';
import { terminologyService } from '@/services/terminology-service';
import type { TermCatalogItem, TermLabels } from '@/types/terminology';
import { useTerminologyListConfig } from './use-terminology-list-config';
import { TermEditDialog } from './term-edit-dialog';

/**
 * Terminology settings (plan sprint-3/08, F10) - rename what entities are called
 * for this tenant, on the full config-driven Resource shell (search · filter ·
 * column visibility/reorder/resize · sort · export). Read for all authenticated
 * users; edit gated terminology.manage. Edit is an inline dialog (no detail page).
 */
export default function TerminologyPage() {
  const [editing, setEditing] = useState<TermCatalogItem | null>(null);
  // Bumping the key remounts ResourceList → it refetches the catalog after a save.
  const [nonce, setNonce] = useState(0);
  const config = useTerminologyListConfig(setEditing);

  const handleSave = async (labels: TermLabels) => {
    if (!editing) return;
    await terminologyService.setTerm(editing.key, labels);
    await refreshTerminology();
    setEditing(null);
    setNonce((n) => n + 1);
  };

  return (
    <RequirePermission permission="terminology.manage">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Rename what entities are called across this workspace.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {editing && (
          <TermEditDialog
            item={editing}
            onClose={() => setEditing(null)}
            onSave={handleSave}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

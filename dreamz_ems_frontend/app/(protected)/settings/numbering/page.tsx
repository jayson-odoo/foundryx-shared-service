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
import { numberingService } from '@/services/numbering-service';
import type { NumberCatalogItem, NumberReset } from '@/types/numbering';
import { useNumberingListConfig } from './use-numbering-list-config';
import { NumberEditDialog } from './number-edit-dialog';

/**
 * Numbering settings (sprint-4/07, Cluster F — AC-07-07) — the per-tenant
 * document-numbering catalog on the full config-driven Resource shell. Read +
 * edit gated numbering.read / numbering.manage. Edit is an inline dialog (no
 * detail page): change prefix / format / reset / next-val → the next generated
 * number reflects it.
 */
export default function NumberingPage() {
  const [editing, setEditing] = useState<NumberCatalogItem | null>(null);
  // Bumping the key remounts ResourceList → refetch the catalog after a save.
  const [nonce, setNonce] = useState(0);
  const config = useNumberingListConfig(setEditing);

  const handleSave = async (
    docType: string,
    body: { prefix: string; formatPattern: string; reset: NumberReset },
    nextVal: number,
    nextValChanged: boolean,
  ) => {
    await numberingService.setFormat(docType, body);
    if (nextValChanged) await numberingService.setNextVal(docType, nextVal);
    setEditing(null);
    setNonce((n) => n + 1);
  };

  return (
    <RequirePermission permission="numbering.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Set the prefix, format and reset cadence for each numbered document.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {editing && (
          <NumberEditDialog
            item={editing}
            onClose={() => setEditing(null)}
            onSave={handleSave}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

'use client';

import { Fragment, useState } from 'react';
import type { NumberCatalogItem, NumberReset } from '@/types/numbering';
import { numberingService } from '@/services/numbering-service';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { NumberEditDialog } from './number-edit-dialog';
import { useNumberingListConfig } from './use-numbering-list-config';

/**
 * Numbering settings (sprint-4/07, Cluster F - AC-07-07) - the per-tenant
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

'use client';

/**
 * Settings > Numbering with the Foundryx UIUX switch on (slice W4-SETTINGS).
 * The same list, the same edit and the same requests as with the switch off
 * (the format PUT, then the next-number PUT only when the number changed);
 * what changes:
 * - After a save the list reloads in place instead of being rebuilt, so its
 *   scroll, search and header filters stay where they were.
 * - A save ends with a done toast. No Undo: the API sets prefix, format and
 *   reset together (an override of only some of them cannot be put back
 *   exactly), and a sequence's next number cannot safely be moved back once
 *   numbers may have been handed out.
 */
import { Fragment, useCallback, useRef, useState } from 'react';
import type { NumberCatalogItem, NumberReset } from '@/types/numbering';
import { toast } from '@/lib/toast';
import { numberingService } from '@/services/numbering-service';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import type { ResourceActionRuntime } from '@/components/platform/resource-list/types';
import { useFxUserName } from '../general/fx-settings-bits';
import { NumberEditDialog } from './number-edit-dialog';
import { useNumberingListConfig } from './use-numbering-list-config';

export function FxNumberingPage() {
  const byWhom = useFxUserName();
  const [editing, setEditing] = useState<NumberCatalogItem | null>(null);
  const runtime = useRef<ResourceActionRuntime | null>(null);
  const onEdit = useCallback((item: NumberCatalogItem, rt?: ResourceActionRuntime) => {
    runtime.current = rt ?? null;
    setEditing(item);
  }, []);
  const config = useNumberingListConfig(onEdit);

  const handleSave = async (
    docType: string,
    body: { prefix: string; formatPattern: string; reset: NumberReset },
    nextVal: number,
    nextValChanged: boolean,
  ) => {
    const label = editing?.label ?? docType;
    await numberingService.setFormat(docType, body);
    if (nextValChanged) await numberingService.setNextVal(docType, nextVal);
    setEditing(null);
    runtime.current?.reload();
    toast.fxDone({
      what: `${label} numbering saved`,
      howMany: nextValChanged ? `next number ${nextVal}` : undefined,
      byWhom,
    });
  };

  return (
    <RequirePermission permission="numbering.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
        {editing && (
          <NumberEditDialog item={editing} onClose={() => setEditing(null)} onSave={handleSave} />
        )}
      </Fragment>
    </RequirePermission>
  );
}

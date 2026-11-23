'use client';

/**
 * Settings > Terminology with the Foundryx UIUX switch on (slice
 * W4-SETTINGS). The same list, the same rename dialog and the same requests
 * as with the switch off; what changes:
 * - After a rename the list reloads in place instead of being rebuilt, so
 *   its scroll, search and header filters stay where they were.
 * - A rename ends with a done toast. Undo puts the earlier name back with the
 *   same endpoints: a reset when the term had its default name, the earlier
 *   names when it had both of its own. A term with only one of its two names
 *   overridden cannot be put back exactly, so it gets no Undo.
 */
import { Fragment, useCallback, useRef, useState } from 'react';
import type { TermCatalogItem, TermLabels } from '@/types/terminology';
import { toast } from '@/lib/toast';
import { refreshTerminology } from '@/hooks/use-terminology';
import { terminologyService } from '@/services/terminology-service';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import type { ResourceActionRuntime } from '@/components/platform/resource-list/types';
import { useFxUserName } from '../general/fx-settings-bits';
import { TermEditDialog } from './term-edit-dialog';
import { fxOverrideLabels, useTerminologyListConfig } from './use-terminology-list-config';

/** How a rename of `item` is put back, or null when it cannot be exactly. */
export function fxRenameUndo(item: TermCatalogItem): (() => Promise<unknown>) | null {
  const untouched = item.overrideSingular === null && item.overridePlural === null;
  if (untouched) return () => terminologyService.resetTerm(item.key);
  const back = fxOverrideLabels(item);
  return back ? () => terminologyService.setTerm(item.key, back) : null;
}

export function FxTerminologyPage() {
  const byWhom = useFxUserName();
  const [editing, setEditing] = useState<TermCatalogItem | null>(null);
  const runtime = useRef<ResourceActionRuntime | null>(null);
  const onEdit = useCallback((item: TermCatalogItem, rt?: ResourceActionRuntime) => {
    runtime.current = rt ?? null;
    setEditing(item);
  }, []);
  const config = useTerminologyListConfig(onEdit);

  const reload = () => runtime.current?.reload();

  const handleSave = async (labels: TermLabels) => {
    if (!editing) return;
    const item = editing;
    await terminologyService.setTerm(item.key, labels);
    await refreshTerminology();
    setEditing(null);
    reload();
    const undo = fxRenameUndo(item);
    toast.fxDone({
      what: `${item.singular} renamed to ${labels.singular}`,
      byWhom,
      undo: undo
        ? () =>
            void undo()
              .then(() => refreshTerminology())
              .then(reload)
              .catch(() => toast.error(`Couldn't undo. ${labels.singular} keeps its new name.`))
        : undefined,
    });
  };

  return (
    <RequirePermission permission="terminology.manage">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
        {editing && (
          <TermEditDialog item={editing} onClose={() => setEditing(null)} onSave={handleSave} />
        )}
      </Fragment>
    </RequirePermission>
  );
}

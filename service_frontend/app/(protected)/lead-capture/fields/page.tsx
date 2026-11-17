'use client';

import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { useLeadFields, useLeadSources } from '@/hooks/use-lead-capture';
import type { FormMapRow } from '@/lib/lead-field-map';
import { AddFormDialog } from './components/add-form-dialog';
import { LeadFieldsCard } from './components/lead-fields-card';
import { MapFieldsDialog, type MapTarget } from './components/map-fields-dialog';
import { useFormMapList } from './components/use-form-map-list';

/**
 * Lead Capture > Fields (lane L-D, AC-64-57): the product's own lead fields and
 * each form's field map (any form question to any of those fields).
 */
export default function LeadCaptureFieldsPage() {
  const { can } = useCan();
  const canManage = can('lead_capture.manage');
  const fields = useLeadFields();
  const sources = useLeadSources();
  const [target, setTarget] = useState<MapTarget | null>(null);
  const [adding, setAdding] = useState(false);
  const [nonce, setNonce] = useState(0);

  const onOpen = useCallback(
    (row: FormMapRow) => setTarget({ sourceId: row.sourceId, formId: row.formId, formName: row.formName }),
    [],
  );
  const onCreate = useCallback(() => setAdding(true), []);
  const config = useFormMapList(onOpen, onCreate);

  const refreshMaps = () => {
    sources.reload();
    setNonce((n) => n + 1);
  };

  return (
    <RequirePermission permission="lead_capture.view">
      <Container width="fluid">
        <PageHeader />
        <div className="flex flex-col gap-5">
          <LeadFieldsCard
            state={fields}
            saving={fields.saving}
            save={fields.save}
            canManage={canManage}
            onSaved={fields.reload}
          />
          <div className="flex flex-col gap-2">
            <h2 className="text-base font-semibold">Form maps</h2>
            <ResourceList key={nonce} config={config} hideHeader />
          </div>
        </div>
      </Container>

      <AddFormDialog open={adding} sources={sources.data ?? []} onOpenChange={setAdding} onPick={setTarget} />
      <MapFieldsDialog
        target={target}
        sources={sources.data ?? []}
        fields={fields.data?.data ?? []}
        canManage={canManage}
        onClose={() => setTarget(null)}
        onSaved={refreshMaps}
      />
    </RequirePermission>
  );
}

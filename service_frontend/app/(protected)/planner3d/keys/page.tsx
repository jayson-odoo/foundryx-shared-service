'use client';

import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { CreateKeyDialog } from './components/create-key-dialog';
import { usePlanner3dKeyList } from './components/use-planner3d-key-list';

/** 3D Planner > Keys (lane PLANNER-3D-S1): the tenant gateway keys (fx3_live_). */
export default function Planner3dKeysPage() {
  const [open, setOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setOpen(true), []);
  const config = usePlanner3dKeyList(onCreate, nonce);

  return (
    <RequirePermission permission="planner3d.keys.manage">
      <Container width="fluid">
        {/* Own header so Create sits on the list's toolbar row (one row:
            Search, Filters, Export, Columns, Create), like Delivery. */}
        <PageHeader />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </Container>
      <CreateKeyDialog open={open} onOpenChange={setOpen} onCreated={() => setNonce((n) => n + 1)} />
    </RequirePermission>
  );
}

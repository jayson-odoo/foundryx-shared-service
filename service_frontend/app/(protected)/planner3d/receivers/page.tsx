'use client';

import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { AddReceiverDialog } from './components/add-receiver-dialog';
import { usePlanner3dReceiverList } from './components/use-planner3d-receiver-list';

/** 3D Planner > Receivers (lane PLANNER-3D-S1, contract 5.1): where the
 *  `model.candidates_ready` / `model.ready` events are pushed. */
export default function Planner3dReceiversPage() {
  const [open, setOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setOpen(true), []);
  const onChanged = useCallback(() => setNonce((n) => n + 1), []);
  const config = usePlanner3dReceiverList(onCreate, onChanged, nonce);

  return (
    <RequirePermission permission="planner3d.webhooks.manage">
      <Container width="fluid">
        <PageHeader />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </Container>
      <AddReceiverDialog open={open} onOpenChange={setOpen} onAdded={onChanged} />
    </RequirePermission>
  );
}

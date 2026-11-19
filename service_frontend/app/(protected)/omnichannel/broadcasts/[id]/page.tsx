'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { useFx } from '@/hooks/use-fx';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { BroadcastFormView } from '../components/broadcast-form-view';
import { BroadcastDoneView } from '../components/broadcast-done-view';
import { clearBroadcastDone, peekBroadcastDone } from '../components/broadcast-done-store';

export default function BroadcastFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';
  const { workspaceId } = useWorkspaceId();
  // Foundryx UIUX switch only: right after a send from this tab, the done
  // page (answers Q3) shows first; "View delivery" leaves it for this page.
  const fx = useFx();
  const [done, setDone] = useState(() => peekBroadcastDone(id));
  useEffect(() => {
    clearBroadcastDone(id);
  }, [id]);
  const viewDelivery = useCallback(() => setDone(null), []);

  if (fx && done) {
    return (
      <RequirePermission permission="broadcasts.read">
        <BroadcastDoneView workspaceId={workspaceId} broadcastId={id} entry={done} onViewDelivery={viewDelivery} />
      </RequirePermission>
    );
  }

  return (
    <RequirePermission permission="broadcasts.read">
      <BroadcastFormView workspaceId={workspaceId} broadcastId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

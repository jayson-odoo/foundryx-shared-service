'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { BroadcastFormView } from '../components/broadcast-form-view';

export default function BroadcastFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';
  const { workspaceId } = useWorkspaceId();

  return (
    <RequirePermission permission="broadcasts.read">
      <BroadcastFormView workspaceId={workspaceId} broadcastId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

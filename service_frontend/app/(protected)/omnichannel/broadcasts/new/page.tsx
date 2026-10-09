'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { BroadcastFormView } from '../components/broadcast-form-view';

export default function NewBroadcastPage() {
  const { workspaceId } = useWorkspaceId();

  return (
    <RequirePermission permission="broadcasts.manage">
      <BroadcastFormView workspaceId={workspaceId} initialEditing />
    </RequirePermission>
  );
}

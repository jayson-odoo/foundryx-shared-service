'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { WorkspaceFormView } from '../components/workspace-form-view';

export default function WorkspaceFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="workspaces.read">
      <WorkspaceFormView workspaceId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

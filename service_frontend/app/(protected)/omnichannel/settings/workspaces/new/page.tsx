'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { WorkspaceFormView } from '../components/workspace-form-view';

export default function NewWorkspacePage() {
  return (
    <RequirePermission permission="workspaces.manage">
      <WorkspaceFormView initialEditing />
    </RequirePermission>
  );
}

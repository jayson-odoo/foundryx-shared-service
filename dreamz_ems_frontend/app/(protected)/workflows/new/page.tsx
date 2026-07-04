'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { WorkflowFormView } from '../components/workflow-form-view';

export default function NewWorkflowPage() {
  return (
    <RequirePermission permission="workflows.manage">
      <WorkflowFormView initialEditing />
    </RequirePermission>
  );
}

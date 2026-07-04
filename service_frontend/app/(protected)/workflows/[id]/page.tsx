'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { WorkflowFormView } from '../components/workflow-form-view';

export default function WorkflowFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';
  const debugRunId = searchParams.get('debug') ?? undefined;

  return (
    <RequirePermission permission="workflows.read">
      <WorkflowFormView workflowId={id} initialEditing={initialEditing} debugRunId={debugRunId} />
    </RequirePermission>
  );
}

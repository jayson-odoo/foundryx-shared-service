'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { AgentFormView } from '../../components/agent-form-view';

export default function AgentFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();

  return (
    <RequirePermission permission="ai_agents.read">
      <AgentFormView
        agentId={String(params.id)}
        initialEditing={searchParams.get('edit') === '1'}
      />
    </RequirePermission>
  );
}

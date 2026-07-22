'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { AgentFormView } from '../../components/agent-form-view';

export default function NewAgentPage() {
  return (
    <RequirePermission permission="ai_agents.manage">
      <AgentFormView initialEditing />
    </RequirePermission>
  );
}

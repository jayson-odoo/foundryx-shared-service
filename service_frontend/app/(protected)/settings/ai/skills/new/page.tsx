'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { SkillFormView } from '../../components/skill-form-view';

export default function NewSkillPage() {
  return (
    <RequirePermission permission="ai_agents.manage">
      <SkillFormView initialEditing />
    </RequirePermission>
  );
}

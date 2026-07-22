'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { SkillFormView } from '../../components/skill-form-view';

export default function SkillFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();

  return (
    <RequirePermission permission="ai_agents.read">
      <SkillFormView
        skillId={String(params.id)}
        initialEditing={searchParams.get('edit') === '1'}
      />
    </RequirePermission>
  );
}

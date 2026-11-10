'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { TeamFormView } from '../components/team-form-view';

export default function TeamFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="teams.read">
      <TeamFormView teamId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

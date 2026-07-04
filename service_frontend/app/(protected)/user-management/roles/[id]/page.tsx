'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { RoleFormView } from '../components/role-form-view';

export default function RoleFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="roles.read">
      <RoleFormView roleId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

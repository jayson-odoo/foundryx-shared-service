'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { UserFormView } from '../components/user-form-view';

export default function UserFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="users.read">
      <UserFormView userId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

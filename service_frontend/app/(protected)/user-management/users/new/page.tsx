'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { UserFormView } from '../components/user-form-view';

export default function NewUserPage() {
  return (
    <RequirePermission permission="users.create">
      <UserFormView initialEditing />
    </RequirePermission>
  );
}

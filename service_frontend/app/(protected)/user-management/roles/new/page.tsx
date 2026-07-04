'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { RoleFormView } from '../components/role-form-view';

export default function NewRolePage() {
  return (
    <RequirePermission permission="roles.create">
      <RoleFormView initialEditing />
    </RequirePermission>
  );
}

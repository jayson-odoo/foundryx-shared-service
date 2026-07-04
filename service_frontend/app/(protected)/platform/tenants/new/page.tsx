'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { TenantFormView } from '../components/tenant-form-view';

export default function NewTenantPage() {
  return (
    <RequirePermission permission="tenants.create">
      <TenantFormView initialEditing />
    </RequirePermission>
  );
}

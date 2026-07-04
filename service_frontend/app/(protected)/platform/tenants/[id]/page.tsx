'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { TenantFormView } from '../components/tenant-form-view';

export default function TenantFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="tenants.read">
      <TenantFormView tenantId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ConnectionFormView } from '../components/connection-form-view';

export default function ConnectionFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="integrations.read">
      <ConnectionFormView connectionId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

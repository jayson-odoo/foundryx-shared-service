'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { FormDetailView } from '../components/form-detail-view';

export default function FormDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="forms.read">
      <FormDetailView formId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

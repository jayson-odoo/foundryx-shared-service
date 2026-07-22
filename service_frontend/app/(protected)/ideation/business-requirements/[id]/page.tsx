'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { BrFormView } from '../components/br-form-view';

export default function BusinessRequirementDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();

  return (
    <RequirePermission permission="ideation.business_requirements.read">
      <BrFormView
        brId={String(params.id)}
        initialEditing={searchParams.get('edit') === '1'}
      />
    </RequirePermission>
  );
}

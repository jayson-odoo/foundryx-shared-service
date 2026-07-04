'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { StatusEntityDetail } from '@/components/platform/status-engine';

export default function PlatformStatusEntityPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const entityType = String(params.entity);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="statuses.read">
      <StatusEntityDetail
        entityType={entityType}
        basePath="/platform/status-engine"
        listLabel="Status Engine"
        initialEditing={initialEditing}
      />
    </RequirePermission>
  );
}

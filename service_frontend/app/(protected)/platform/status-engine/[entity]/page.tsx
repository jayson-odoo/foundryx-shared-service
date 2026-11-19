'use client';

import { useParams, useSearchParams } from 'next/navigation';
import type { StatusEntity } from '@/types/status-engine';
import { RequirePermission } from '@/components/common/require-permission';
import type { FxFormConfig } from '@/components/platform/resource-form/types';
import { StatusEntityDetail } from '@/components/platform/status-engine';

/**
 * Foundryx UIUX switch only (slice W3-PLATFORM); ignored while off. Record
 * chrome only: Edit at rest and Save while editing as the red action;
 * Simulate date beside it. The status machine canvas is an SS difference and is untouched.
 */
const PLATFORM_ENTITY_FX: FxFormConfig<StatusEntity> = {
  mainActionId: 'save',
};

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
        fx={PLATFORM_ENTITY_FX}
      />
    </RequirePermission>
  );
}

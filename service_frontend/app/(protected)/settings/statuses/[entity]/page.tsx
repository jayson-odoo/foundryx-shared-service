'use client';

import { useParams, useSearchParams } from 'next/navigation';
import type { StatusEntity } from '@/types/status-engine';
import { RequirePermission } from '@/components/common/require-permission';
import type { FxFormConfig } from '@/components/platform/resource-form/types';
import { StatusEntityDetail } from '@/components/platform/status-engine';

/**
 * Foundryx UIUX switch only (slice W4-SETTINGS); ignored while off. Record
 * chrome only: Edit at rest and Save while editing as the red action. The
 * status machine canvas is an SS difference and is untouched.
 */
const TENANT_ENTITY_FX: FxFormConfig<StatusEntity> = {
  mainActionId: 'save',
};

export default function TenantStatusEntityPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const entityType = String(params.entity);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="statuses.read">
      <StatusEntityDetail
        entityType={entityType}
        basePath="/settings/statuses"
        listLabel="Statuses"
        initialEditing={initialEditing}
        fx={TENANT_ENTITY_FX}
      />
    </RequirePermission>
  );
}

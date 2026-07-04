'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ModuleDetail } from './module-detail';

/** App Store module detail route — facts + lifecycle actions (own tenant). */
export default function ModuleDetailPage() {
  const params = useParams<{ name: string }>();
  return (
    <RequirePermission permission="app_store.read">
      <ModuleDetail name={params.name} />
    </RequirePermission>
  );
}

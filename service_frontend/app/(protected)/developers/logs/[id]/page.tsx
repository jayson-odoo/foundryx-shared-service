'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { LogDetailView } from '../components/log-detail-view';

export default function DeveloperLogDetailPage() {
  const params = useParams();
  const id = String(params.id);

  return (
    <RequirePermission permission="integration_logs.read">
      <LogDetailView logId={id} />
    </RequirePermission>
  );
}

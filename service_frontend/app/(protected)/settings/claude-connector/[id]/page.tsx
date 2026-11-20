'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { GrantDetailView } from '../components/grant-detail-view';

export default function ClaudeConnectorGrantPage() {
  const params = useParams();
  return (
    <RequirePermission permission="connector.read">
      <GrantDetailView grantId={String(params.id)} />
    </RequirePermission>
  );
}

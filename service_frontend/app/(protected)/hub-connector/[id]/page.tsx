'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { HUB_VIEW } from '../components/hub-meta';
import { HubDetailView } from './components/hub-detail-view';

export default function HubDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequirePermission permission={HUB_VIEW}>
      <HubDetailView hubId={id} />
    </RequirePermission>
  );
}

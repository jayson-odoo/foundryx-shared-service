'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { TraceDetailView } from '../../components/trace-detail-view';

export default function TraceDetailPage() {
  const params = useParams();

  return (
    <RequirePermission permission="ai_traces.read">
      <TraceDetailView traceId={String(params.id)} />
    </RequirePermission>
  );
}

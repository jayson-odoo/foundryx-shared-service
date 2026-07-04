'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { LeadDetail } from './lead-detail';

/** Lead detail route — view/edit fields + status change + Won→create-event. */
export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="crm_leads.read">
      <LeadDetail leadId={params.id} />
    </RequirePermission>
  );
}

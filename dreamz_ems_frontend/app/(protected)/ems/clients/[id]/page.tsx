'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ClientDetail } from './client-detail';

/** Client detail route — view/edit fields + status change. */
export default function ClientDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="crm_clients.read">
      <ClientDetail clientId={params.id} />
    </RequirePermission>
  );
}

'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { QuotationDetail } from './quotation-detail';

export default function QuotationDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="crm_quotations.read">
      <QuotationDetail quotationId={params.id} />
    </RequirePermission>
  );
}

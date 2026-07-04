'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { SalesOrderDetail } from './sales-order-detail';

export default function SalesOrderDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="crm_sales_orders.read">
      <SalesOrderDetail salesOrderId={params.id} />
    </RequirePermission>
  );
}

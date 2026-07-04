'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ProductDetail } from './product-detail';

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="products.read">
      <ProductDetail productId={params.id} />
    </RequirePermission>
  );
}

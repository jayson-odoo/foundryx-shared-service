'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ProductFormView } from '../../components/product-form-view';

export default function ConnectorProductPage() {
  const params = useParams();
  const initialEditing = useSearchParams().get('edit') === '1';
  return (
    <RequirePermission permission="connector.read">
      <ProductFormView productKey={String(params.key)} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

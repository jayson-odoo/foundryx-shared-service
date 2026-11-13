'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { ProductFormView } from '../../components/product-form-view';

export default function NewConnectorProductPage() {
  return (
    <RequirePermission permission="connector.settings">
      <ProductFormView initialEditing />
    </RequirePermission>
  );
}

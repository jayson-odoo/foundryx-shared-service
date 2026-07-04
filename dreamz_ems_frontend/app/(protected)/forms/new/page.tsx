'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { FormDetailView } from '../components/form-detail-view';

export default function NewFormPage() {
  return (
    <RequirePermission permission="forms.manage">
      <FormDetailView initialEditing />
    </RequirePermission>
  );
}

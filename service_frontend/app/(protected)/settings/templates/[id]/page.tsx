'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { TemplateFormView } from '../components/template-form-view';

export default function TemplateFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="templates.read">
      <TemplateFormView templateId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}

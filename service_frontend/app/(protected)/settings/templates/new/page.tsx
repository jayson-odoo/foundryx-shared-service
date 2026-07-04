'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { TemplateFormView } from '../components/template-form-view';

export default function NewTemplatePage() {
  return (
    <RequirePermission permission="templates.manage">
      <TemplateFormView initialEditing />
    </RequirePermission>
  );
}

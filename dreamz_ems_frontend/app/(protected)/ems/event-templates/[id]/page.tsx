'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { TemplateDetail } from './template-detail';

/** Event Template detail route — Details + eligibility-flow editor (AC-11-12). */
export default function TemplateDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="project_templates.read">
      <TemplateDetail templateId={params.id} />
    </RequirePermission>
  );
}

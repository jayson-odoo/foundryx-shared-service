import { RequirePermission } from '@/components/common/require-permission';
import { TemplateBuilderView } from '../components/template-builder-view';

export default async function EditTemplatePage({
  params,
}: {
  params: Promise<{ id: string; templateId: string }>;
}) {
  const { id, templateId } = await params;
  return (
    <RequirePermission permission="wa_templates.read">
      <TemplateBuilderView channelId={id} templateId={templateId} />
    </RequirePermission>
  );
}

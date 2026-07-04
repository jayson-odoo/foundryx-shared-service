import { RequirePermission } from '@/components/common/require-permission';
import { TemplateBuilderView } from '../components/template-builder-view';

export default async function NewTemplatePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequirePermission permission="wa_templates.manage">
      <TemplateBuilderView channelId={id} />
    </RequirePermission>
  );
}

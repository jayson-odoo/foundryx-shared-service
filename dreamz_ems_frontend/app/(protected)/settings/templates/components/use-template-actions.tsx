'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Copy, Pencil, RotateCcw, Send, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { templateEngineService } from '@/services/template-service';
import type { TemplateListItem } from '@/types/templates';
import { templatePath } from './paths';

/** ONE action registry — row `…`, bulk dropdown and form `…` all share it. */
export function useTemplateActions(): ResourceAction<TemplateListItem>[] {
  const router = useRouter();

  return useMemo<ResourceAction<TemplateListItem>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true },
        permission: 'templates.manage',
        run: ([template]) => {
          router.push(`${templatePath(template.id)}?edit=1`);
        },
      },
      {
        id: 'duplicate',
        label: 'Duplicate',
        icon: Copy,
        surfaces: { row: true, form: true },
        permission: 'templates.manage',
        run: async ([template], runtime) => {
          const copy = await templateEngineService.duplicateTemplate(template.id);
          toast.success(`Duplicated as "${copy.name}".`);
          runtime.reload();
        },
      },
      {
        id: 'test-send',
        label: 'Send test email',
        icon: Send,
        surfaces: { row: true, form: true },
        permission: 'templates.manage',
        run: async ([template]) => {
          const { toEmail } = await templateEngineService.testSend(template.id);
          toast.success(`Test email queued to ${toEmail}.`);
        },
      },
      {
        id: 'reset',
        label: 'Reset to default',
        icon: RotateCcw,
        surfaces: { row: true, form: true },
        permission: 'templates.manage',
        // Only forked system templates have a platform default to reset to.
        isVisible: (rows) => rows.every((t) => t.isSystem && t.tier === 'customized'),
        confirm: {
          title: 'Reset to platform default?',
          description:
            'Your customized design will be replaced by the platform default. This cannot be undone.',
          confirmLabel: 'Reset',
        },
        run: async ([template], runtime) => {
          await templateEngineService.resetTemplate(template.id);
          toast.success(`"${template.name}" reset to the platform default.`);
          runtime.reload();
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true, form: true },
        permission: 'templates.manage',
        // System templates are delete-blocked (D6) — reset instead.
        isVisible: (rows) => rows.every((t) => !t.isSystem),
        confirm: {
          title: 'Delete template?',
          description: 'Emails referencing this template will fail to render. This cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          for (const template of rows) {
            await templateEngineService.deleteTemplate(template.id);
          }
          toast.success(`Deleted ${rows.length} template(s).`);
          runtime.reload();
        },
      },
    ],
    [router],
  );
}

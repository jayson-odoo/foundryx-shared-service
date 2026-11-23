'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Copy, Pencil, RotateCcw, Send, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ResourceAction } from '@/components/platform/resource-list';
import { templateEngineService } from '@/services/template-service';
import type { TemplateListItem } from '@/types/templates';
import { templatePath } from './paths';
import { useFx } from '@/hooks/use-fx';
import { useFxActor } from '@/components/fx/pages/w4-templates/use-fx-actor';

/** ONE action registry - row `…`, bulk dropdown and form `…` all share it. */
export function useTemplateActions(): ResourceAction<TemplateListItem>[] {
  const router = useRouter();
  const fx = useFx();
  const byWhom = useFxActor();

  const actions = useMemo<ResourceAction<TemplateListItem>[]>(
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
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `templates.reset` handler commits it).
        deferred: { actionKey: 'templates.reset', entityType: 'template' },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true, form: true },
        permission: 'templates.manage',
        // System templates are delete-blocked (D6) - reset instead.
        isVisible: (rows) => rows.every((t) => !t.isSystem),
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `templates.delete` handler commits it).
        deferred: { actionKey: 'templates.delete', entityType: 'template' },
      },
    ],
    [router],
  );

  // Foundryx UIUX switch only: the same actions and the same requests; only
  // what is said afterwards changes (toasts name what, for whom and by whom;
  // the countdown names the template).
  return useMemo(
    () => (fx ? actions.map((a) => fxTemplateAction(a, byWhom)) : actions),
    [fx, actions, byWhom],
  );
}

function fxTemplateAction(
  action: ResourceAction<TemplateListItem>,
  byWhom: string | undefined,
): ResourceAction<TemplateListItem> {
  if (action.id === 'duplicate') {
    return {
      ...action,
      run: async ([template], runtime) => {
        const copy = await templateEngineService.duplicateTemplate(template.id);
        toast.fxDone({ what: `${template.name} duplicated as ${copy.name}`, byWhom });
        runtime.reload();
      },
    } as ResourceAction<TemplateListItem>;
  }
  if (action.id === 'test-send') {
    return {
      ...action,
      run: async ([template]) => {
        const { toEmail } = await templateEngineService.testSend(template.id);
        toast.fxDone({ what: `Test of ${template.name} queued`, forWhom: `to ${toEmail}`, byWhom });
      },
    } as ResourceAction<TemplateListItem>;
  }
  if (action.deferred) {
    return {
      ...action,
      deferred: {
        ...action.deferred,
        fxName: (rows: TemplateListItem[]) => (rows.length === 1 ? rows[0].name : undefined),
      },
    };
  }
  return action;
}

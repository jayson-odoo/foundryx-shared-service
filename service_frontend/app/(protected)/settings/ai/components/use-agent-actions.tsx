'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { aiService } from '@/services/ai-service';
import type { AiAgent } from '@/types/ai';
import { agentPath } from './paths';

/** ONE action registry - row `…`, bulk dropdown and form `…` share it. */
export function useAgentActions(): ResourceAction<AiAgent>[] {
  const router = useRouter();

  return useMemo<ResourceAction<AiAgent>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true },
        permission: 'ai_agents.manage',
        run: ([agent]) => router.push(`${agentPath(agent.id)}?edit=1`),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true, form: true },
        permission: 'ai_agents.manage',
        confirm: {
          title: 'Delete agent?',
          description:
            'Runs already recorded keep their trace history. This cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          for (const agent of rows) await aiService.removeAgent(agent.id);
          toast.success(`Deleted ${rows.length} agent${rows.length === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
    ],
    [router],
  );
}

'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Trash2 } from 'lucide-react';
import type { ResourceAction } from '@/components/platform/resource-list';
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
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `ai_agents.delete` handler commits it).
        deferred: { actionKey: 'ai_agents.delete', entityType: 'ai_agent' },
      },
    ],
    [router],
  );
}

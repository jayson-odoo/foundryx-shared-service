'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Trash2 } from 'lucide-react';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { Team } from '@/types/team';
import { teamFormHref } from './paths';

/**
 * The Team action registry (Users clone, D-A8-2) - Edit + Delete, surfaced in
 * the row "…" menu, the bulk toolbar, and the form "…" menu.
 *
 * Teams have NO soft-trash (D-A8-15/19 - a team is either active or inactive,
 * never trashed), but Delete is still a hard-destructive mutation, so it
 * rides the SAME grace-window `deferred` engine every other hard delete does
 * (review round 1, finding 3 - the earlier plain `confirm` ask-once carve-out
 * was an unregistered escape hatch, not a disclosed one). The registered
 * `teams.delete` handler (`app/deferred_actions/handlers.py`) calls
 * `TeamService.delete`, which still runs the reference-guard check (a team
 * assigned to live conversations 409s on the SYNCHRONOUS route) - here it
 * surfaces as a `failed` countdown with a counts-formatted message via the
 * shell's `onFailed` toast, never a raw `team_in_use` token.
 */
export function useTeamActions(): ResourceAction<Team>[] {
  const router = useRouter();

  return useMemo<ResourceAction<Team>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'teams.manage',
        surfaces: { row: true },
        run: ([team], rt) => {
          if (!team) return;
          router.push(teamFormHref(team.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'teams.manage',
        surfaces: { row: true, bulk: true, form: true },
        // Grace-window deferred action (sprint-4/23 T5, D2) - no confirm
        // dialog, no `run` (the registered `teams.delete` handler commits it
        // server-side); the form surface's commit navigates via
        // ResourceForm's own `backHref`-aware handler (AC-DLA-30), row/bulk
        // stay put + reload.
        deferred: { actionKey: 'teams.delete', entityType: 'team' },
      },
    ],
    [router],
  );
}

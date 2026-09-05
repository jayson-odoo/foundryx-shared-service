'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction } from '@/components/platform/resource-list';
import { teamService } from '@/services/team-service';
import type { Team } from '@/types/team';
import { teamFormHref } from './paths';

/** Structured 409 body a blocked delete carries (§5.1 `409 body`). */
interface TeamInUseDetail {
  error?: string;
  counts?: Record<string, number>;
}

function formatCounts(counts: Record<string, number> | undefined): string {
  const entries = Object.entries(counts ?? {});
  if (!entries.length) return 'other records';
  return entries.map(([source, n]) => `${n} ${source}`).join(', ');
}

/**
 * The Team action registry (Users clone, D-A8-2) - Edit + Delete, surfaced in
 * the row "…" menu, the bulk toolbar, and the form "…" menu.
 *
 * Delete has NO soft-trash (D-A8-15/19 - a team is either active or inactive,
 * never trashed) so the grace-window `deferred` engine doesn't apply, and it
 * is the FIRST production use of a core reference guard (409 `team_in_use`
 * with per-source counts, §3.1) - a concept `ResourceAction.confirm`'s typed
 * carve-out list (`confirm-carve-outs.inventory.test.ts`) didn't have a slot
 * for yet, so this stays a PLAIN `confirm` (ask once) + the blocked-count
 * detail surfaces via `toast.error` after the attempt (no destructive call
 * fires when blocked - AC-TEM-42). Flagged for the reviewer/user in the S0
 * report rather than silently reusing an unrelated carve-out.
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
        confirm: {
          title: 'Delete this team?',
          description: 'This cannot be undone. A team still assigned to conversations cannot be deleted.',
          confirmLabel: 'Delete',
        },
        run: async (rows, rt) => {
          let deleted = 0;
          const blocked: string[] = [];
          for (const team of rows) {
            try {
              await teamService.remove(team.id);
              deleted += 1;
            } catch (e) {
              if (e instanceof ApiError && e.status === 409) {
                const detail = e.detail as TeamInUseDetail | undefined;
                blocked.push(`"${team.name}" is in use by ${formatCounts(detail?.counts)}`);
              } else {
                toast.error(e instanceof Error ? e.message : `Could not delete "${team.name}".`);
              }
            }
          }
          if (deleted > 0) toast.success(`Deleted ${deleted} team(s).`);
          if (blocked.length > 0) {
            toast.error(`Could not delete: ${blocked.join('; ')}. Reassign them first.`);
          }
          rt.reload();
        },
      },
    ],
    [router],
  );
}

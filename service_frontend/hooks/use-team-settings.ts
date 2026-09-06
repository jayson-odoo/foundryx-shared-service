'use client';

/**
 * Per-team assignment-strategy state (plan 28, roadmap A8, AC-TEM-28) - backs
 * the workspace "Team assignment" tab. `GET .../team-settings` now returns
 * one row per ACTIVE core team (resolved via the module's `team_directory.
 * list_active`, no `teams.read` permission needed) already merged with this
 * workspace's configured strategy rows - a never-configured team defaults to
 * `round_robin` server-side (review round 1, finding 4/5/6). This hook no
 * longer calls `useTeams()` (`GET /teams`, gated `teams.read`) to build the
 * roster - a caller holding only `conversations.read`/`conversations.assign`
 * can now populate the whole tab.
 */
import { useCallback, useEffect, useState } from 'react';

import { teamSettingsService } from '@/services/team-settings-service';
import type { TeamAssignmentSetting, TeamAssignmentStrategy } from '@/types/omnichannel';

export type TeamSettingsRow = TeamAssignmentSetting;

export interface UseTeamSettingsResult {
  rows: TeamSettingsRow[];
  isLoading: boolean;
  error: string | null;
  setStrategy: (teamId: string, strategy: TeamAssignmentStrategy) => Promise<void>;
  reload: () => void;
}

export function useTeamSettings(workspaceId: string | null): UseTeamSettingsResult {
  const [rows, setRows] = useState<TeamSettingsRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(() => {
    if (!workspaceId) {
      setRows([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    teamSettingsService
      .list(workspaceId)
      .then(setRows)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load team assignment settings.'))
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, nonce]);

  useEffect(load, [load]);

  const setStrategy = useCallback(
    async (teamId: string, strategy: TeamAssignmentStrategy) => {
      if (!workspaceId) return;
      const updated = await teamSettingsService.setStrategy(workspaceId, teamId, strategy);
      setRows((prev) => prev.map((r) => (r.teamId === teamId ? updated : r)));
    },
    [workspaceId],
  );

  return {
    rows,
    isLoading,
    error,
    setStrategy,
    reload: () => setNonce((n) => n + 1),
  };
}

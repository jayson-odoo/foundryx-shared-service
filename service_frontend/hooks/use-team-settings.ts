'use client';

/**
 * Per-team assignment-strategy state (plan 28, roadmap A8, AC-TEM-28) - backs
 * the workspace "Team assignment" tab. `GET .../team-settings` only returns
 * rows that have EVER been configured or assigned in this workspace, so this
 * hook merges it onto the tenant's full ACTIVE team catalog (`useTeams`) -
 * every active team gets a row, defaulting to `round_robin` when unconfigured
 * (mirrors the backend's own "no row = round_robin" default, AC-TEM-28).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTeams } from '@/hooks/use-teams';
import { teamSettingsService } from '@/services/team-settings-service';
import type { TeamAssignmentSetting, TeamAssignmentStrategy } from '@/types/omnichannel';

export interface TeamSettingsRow extends TeamAssignmentSetting {
  isConfigured: boolean;
}

export interface UseTeamSettingsResult {
  rows: TeamSettingsRow[];
  isLoading: boolean;
  error: string | null;
  setStrategy: (teamId: string, strategy: TeamAssignmentStrategy) => Promise<void>;
  reload: () => void;
}

export function useTeamSettings(workspaceId: string | null): UseTeamSettingsResult {
  const { teams, isLoading: teamsLoading } = useTeams();
  const [settings, setSettings] = useState<TeamAssignmentSetting[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(() => {
    if (!workspaceId) {
      setSettings([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    teamSettingsService
      .list(workspaceId)
      .then(setSettings)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load team assignment settings.'))
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, nonce]);

  useEffect(load, [load]);

  const rows = useMemo<TeamSettingsRow[]>(() => {
    const byTeam = new Map(settings.map((s) => [s.teamId, s]));
    return teams.map((team) => {
      const configured = byTeam.get(team.id);
      return {
        teamId: team.id,
        teamName: team.name,
        strategy: configured?.strategy ?? 'round_robin',
        lastAssignedUserId: configured?.lastAssignedUserId ?? null,
        updatedAt: configured?.updatedAt ?? team.updatedAt,
        isConfigured: !!configured,
      };
    });
  }, [teams, settings]);

  const setStrategy = useCallback(
    async (teamId: string, strategy: TeamAssignmentStrategy) => {
      if (!workspaceId) return;
      const updated = await teamSettingsService.setStrategy(workspaceId, teamId, strategy);
      setSettings((prev) => {
        const rest = prev.filter((s) => s.teamId !== teamId);
        return [...rest, updated];
      });
    },
    [workspaceId],
  );

  return {
    rows,
    isLoading: isLoading || teamsLoading,
    error,
    setStrategy,
    reload: () => setNonce((n) => n + 1),
  };
}

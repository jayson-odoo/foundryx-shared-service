'use client';

/**
 * All (tenant-scoped) teams, active-first - backs any "pick a team" surface
 * that isn't scoped to the caller's own teams (the workflow canvas `team`
 * field, the inbox rail's "All teams" group for `conversations.assign`
 * holders). Plan 28 (roadmap A8).
 */
import { useCallback, useEffect, useState } from 'react';

import { teamService } from '@/services/team-service';
import type { Team } from '@/types/team';

export interface UseTeamsOptions {
  /** Exclude inactive teams (foolproof-UI: an inactive team is never a valid
   *  assignment target). Default true. */
  activeOnly?: boolean;
  /** `GET /teams` requires `teams.read` server-side (review round 1, finding
   *  4/5/6) - callers that render for a caller who may lack it (e.g. an
   *  inbox agent) must pass `enabled: can('teams.read')` so this hook never
   *  fires the request and 403s. Default true (existing admin surfaces are
   *  already permission-gated by their page). Disabling returns an empty,
   *  non-loading result rather than skipping the hook call (hooks can't be
   *  conditional). */
  enabled?: boolean;
}

export interface UseTeamsResult {
  teams: Team[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

export function useTeams(options?: UseTeamsOptions): UseTeamsResult {
  const activeOnly = options?.activeOnly ?? true;
  const enabled = options?.enabled ?? true;
  const [teams, setTeams] = useState<Team[]>([]);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(() => {
    if (!enabled) {
      setTeams([]);
      setIsLoading(false);
      setError(null);
      return;
    }
    setIsLoading(true);
    setError(null);
    teamService
      .list({ page: 0, pageSize: 200, sort: { id: 'name', desc: false } })
      .then((res) => setTeams(activeOnly ? res.data.filter((t) => t.isActive) : res.data))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load teams.'))
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOnly, enabled, nonce]);

  useEffect(load, [load]);

  return { teams, isLoading, error, reload: () => setNonce((n) => n + 1) };
}

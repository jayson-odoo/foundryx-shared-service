'use client';

/**
 * The signed-in user's own teams (`GET /teams/mine` - no `teams.read` needed,
 * D-A8-16) - backs the omnichannel inbox rail's "My teams" section so any
 * agent can find their Team Inbox without the admin read permission. Plan 28.
 */
import { useCallback, useEffect, useState } from 'react';

import { teamService } from '@/services/team-service';
import type { Team } from '@/types/team';

export interface UseMyTeamsResult {
  teams: Team[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

export function useMyTeams(): UseMyTeamsResult {
  const [teams, setTeams] = useState<Team[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(() => {
    setIsLoading(true);
    setError(null);
    teamService
      .mine()
      .then(setTeams)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load your teams.'))
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  useEffect(load, [load]);

  return { teams, isLoading, error, reload: () => setNonce((n) => n + 1) };
}

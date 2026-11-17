'use client';

/** Operator followers of one feedback item (lane FEEDBACK-SUBSCRIBE).
 * UI -> this hook -> `ideaFollowerService` -> api-client. */
import { useCallback, useEffect, useState } from 'react';
import { ideaFollowerService } from '@/services/idea-follower-service';
import type { IdeaFollower } from '@/types/ideation';

export interface UseIdeaFollowers {
  /** null while loading. */
  followers: IdeaFollower[] | null;
  error: string | null;
  reload: () => void;
  add: (contactId: string) => Promise<void>;
  remove: (contactIds: string[]) => Promise<void>;
}

export function useIdeaFollowers(ideaId: string): UseIdeaFollowers {
  const [followers, setFollowers] = useState<IdeaFollower[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    ideaFollowerService
      .list(ideaId)
      .then((rows) => active && setFollowers(rows))
      .catch((e: unknown) => {
        if (!active) return;
        setFollowers([]);
        setError(e instanceof Error ? e.message : 'Could not load followers.');
      });
    return () => {
      active = false;
    };
  }, [ideaId, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  // A follower can change from another window (a contact following from their
  // own board): refetch when this window regains focus (crew pass 70e96f2b).
  useEffect(() => {
    const onFocus = () => setTick((t) => t + 1);
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, []);
  const add = useCallback(
    async (contactId: string) => {
      setFollowers(await ideaFollowerService.add(ideaId, contactId));
    },
    [ideaId],
  );
  const remove = useCallback(
    async (contactIds: string[]) => {
      // Same single-row call per contact (bulk reuses the single action).
      for (const id of contactIds) await ideaFollowerService.remove(ideaId, id);
      setTick((t) => t + 1);
    },
    [ideaId],
  );
  return { followers, error, reload, add, remove };
}

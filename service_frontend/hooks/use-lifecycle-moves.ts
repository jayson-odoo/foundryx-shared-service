'use client';

/**
 * The fireable outgoing lifecycle edges from a contact's CURRENT stage (plan
 * 25, AC-CDM-18) - the ONLY options the "Move to" picker may offer
 * (foolproof-UI: never list a move that would 409). Refetches whenever the
 * contact's stage changes (so a move immediately narrows to the new stage's
 * own outgoing edges).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import { conversationService } from '@/services/conversation-service';
import type { LifecycleMove } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Could not load the available moves.';
}

export interface UseLifecycleMovesResult {
  moves: LifecycleMove[];
  loading: boolean;
  /** F5 (plan-25 round-3 codex triage): force a refetch outside the
   *  dependency changes below - the caller uses this after a REJECTED move
   *  (409), since that means the cached fireable list already disagreed
   *  with the server. */
  refetch: () => void;
}

export function useLifecycleMoves(
  contactId: string | null | undefined,
  /** Bust the cache when the contact's OWN stage key changes (a move should
   *  immediately re-narrow to the new stage's outgoing edges). */
  stageKey: string | null | undefined,
  /** F5: an additional cheap "did the record change" signal - a rule-engine
   *  condition on an outgoing edge can reference ANY contact field, not just
   *  the stage, so the fireable set can shift even when `stageKey` hasn't
   *  moved. The caller passes a fingerprint of the condition-relevant fields
   *  (e.g. priority/assignee/CSW) so any of THOSE changing busts the cache
   *  too. */
  changeSignal?: string | null,
): UseLifecycleMovesResult {
  const [moves, setMoves] = useState<LifecycleMove[]>([]);
  const [loading, setLoading] = useState(true);
  const [refetchSeq, setRefetchSeq] = useState(0);

  useEffect(() => {
    if (!contactId) {
      setMoves([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    conversationService
      .lifecycleMoves(contactId)
      .then((data) => !cancelled && setMoves(data))
      .catch((error) => {
        if (!cancelled) {
          setMoves([]);
          toast.error(describe(error));
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [contactId, stageKey, changeSignal, refetchSeq]);

  const refetch = useCallback(() => setRefetchSeq((n) => n + 1), []);

  return { moves, loading, refetch };
}

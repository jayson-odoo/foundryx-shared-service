'use client';

/**
 * One thread's event history (plan 27, AC-IVE-13) - backs the drawer's
 * Activities feed (merged with the SYSTEM notes `useMessages` already loads).
 * Fetches on `contactId` change; `reload()` lets the drawer refresh after a
 * mutation (close/reopen/assign) that isn't itself pushed over the socket.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import type { ConversationEvent } from '@/types/omnichannel';

export interface UseThreadEventsResult {
  events: ConversationEvent[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

export function useThreadEvents(contactId: string | null | undefined): UseThreadEventsResult {
  const [events, setEvents] = useState<ConversationEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchSeq = useRef(0);

  const load = useCallback(() => {
    if (!contactId) {
      setEvents([]);
      return;
    }
    const seq = ++fetchSeq.current;
    setIsLoading(true);
    setError(null);
    conversationService
      .listEvents(contactId)
      .then((list) => {
        if (seq !== fetchSeq.current) return;
        setEvents(list);
      })
      .catch((e: unknown) => {
        if (seq !== fetchSeq.current) return;
        setError(e instanceof Error ? e.message : 'Could not load the activity history');
      })
      .finally(() => {
        if (seq === fetchSeq.current) setIsLoading(false);
      });
  }, [contactId]);

  useEffect(load, [load]);

  return { events, isLoading, error, reload: load };
}

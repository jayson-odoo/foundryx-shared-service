'use client';

/**
 * Broadcast recipients state (plan 29) - backs the detail form's Recipients
 * tab (an embedded Resource list, AC-BRD-10). Server-side (mock) paginated,
 * filterable by state, searchable by contact name/phone.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { broadcastService, type RecipientQuery } from '@/services/broadcast-service';
import type { BroadcastRecipient } from '@/types/omnichannel';
import type { ListResult } from '@/types/resource';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseBroadcastRecipientsResult {
  fetcher: (query: RecipientQuery) => Promise<ListResult<BroadcastRecipient>>;
  reload: () => void;
  reloadToken: number;
}

/** Returns a stable fetcher bound to (workspaceId, broadcastId) - suitable for
 *  an embedded `ResourceList`'s `fetcher` prop. `reload()` bumps a token the
 *  caller can key the embedded list on to force a refetch after a mutation. */
export function useBroadcastRecipients(
  workspaceId: string | null,
  broadcastId: string | null,
): UseBroadcastRecipientsResult {
  const [reloadToken, setReloadToken] = useState(0);

  const fetcher = useCallback(
    async (query: RecipientQuery) => {
      if (!workspaceId || !broadcastId) return { data: [], total: 0, page: query.page };
      try {
        return await broadcastService.recipients(workspaceId, broadcastId, query);
      } catch (error) {
        toast.error(describe(error));
        return { data: [], total: 0, page: query.page };
      }
    },
    [workspaceId, broadcastId],
  );

  const reload = useCallback(() => setReloadToken((t) => t + 1), []);

  // Recipients on a SENDING broadcast advance via the mock's wall-clock timer
  // (see broadcast-service.mock.ts `tick`) - poll gently so the tab reflects
  // progress without the caller wiring a real socket in S0.
  useEffect(() => {
    if (!workspaceId || !broadcastId) return;
    const interval = setInterval(() => setReloadToken((t) => t + 1), 5000);
    return () => clearInterval(interval);
  }, [workspaceId, broadcastId]);

  return { fetcher, reload, reloadToken };
}

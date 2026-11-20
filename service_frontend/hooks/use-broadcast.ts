'use client';

/**
 * Single-broadcast state (plan 29) - loads a broadcast by id, exposes a
 * refresh (used after Send/Cancel/Duplicate actions on the detail form).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { broadcastService } from '@/services/broadcast-service';
import type { Broadcast } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseBroadcastResult {
  broadcast: Broadcast | null;
  loading: boolean;
  notFound: boolean;
  refresh: () => Promise<void>;
}

export function useBroadcast(workspaceId: string | null, broadcastId: string | undefined): UseBroadcastResult {
  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const refresh = useCallback(async () => {
    if (!workspaceId || !broadcastId) return;
    try {
      setBroadcast(await broadcastService.get(workspaceId, broadcastId));
      setNotFound(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) setNotFound(true);
      else toast.error(describe(error));
    }
  }, [workspaceId, broadcastId]);

  useEffect(() => {
    if (!broadcastId) {
      setLoading(false);
      return;
    }
    if (!workspaceId) return;
    let cancelled = false;
    setLoading(true);
    broadcastService
      .get(workspaceId, broadcastId)
      .then((row) => !cancelled && setBroadcast(row))
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) setNotFound(true);
        else toast.error(describe(error));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId, broadcastId]);

  return { broadcast, loading, notFound, refresh };
}

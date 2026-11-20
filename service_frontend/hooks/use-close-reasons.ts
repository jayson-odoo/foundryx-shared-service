'use client';

/**
 * Close-reason state (plan 27) - backs the workspace Settings -> Close
 * reasons tab (CRUD) AND the drawer's Close dialog (active-only picker).
 * Mirrors `use-contact-tags.ts` exactly.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { closeReasonService } from '@/services/close-reason-service';
import type { CloseReason, CreateCloseReasonInput, UpdateCloseReasonInput } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseCloseReasonsResult {
  reasons: CloseReason[];
  loading: boolean;
  refresh: () => Promise<void>;
  create: (input: CreateCloseReasonInput) => Promise<CloseReason>;
  update: (id: string, input: UpdateCloseReasonInput) => Promise<CloseReason>;
}

export function useCloseReasons(workspaceId: string | null): UseCloseReasonsResult {
  const [reasons, setReasons] = useState<CloseReason[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setReasons([]);
      return;
    }
    try {
      setReasons(await closeReasonService.list(workspaceId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [workspaceId]);

  useEffect(() => {
    setReasons([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    closeReasonService
      .list(workspaceId)
      .then((data) => !cancelled && setReasons(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const create = useCallback(
    async (input: CreateCloseReasonInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await closeReasonService.create(workspaceId, input);
      await refresh();
      return created;
    },
    [workspaceId, refresh],
  );

  const update = useCallback(
    async (id: string, input: UpdateCloseReasonInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await closeReasonService.update(workspaceId, id, input);
      await refresh();
      return updated;
    },
    [workspaceId, refresh],
  );

  return { reasons, loading, refresh, create, update };
}

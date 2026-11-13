'use client';

/**
 * Saved-view state (plan 27) - backs the inbox view rail's Views section +
 * the save-view dialog. Mirrors `use-contact-tags.ts` / `use-close-reasons.ts`.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { inboxViewService } from '@/services/inbox-view-service';
import type { CreateInboxViewInput, InboxView, UpdateInboxViewInput } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseInboxViewsResult {
  views: InboxView[];
  loading: boolean;
  refresh: () => Promise<void>;
  create: (input: CreateInboxViewInput) => Promise<InboxView>;
  update: (id: string, input: UpdateInboxViewInput) => Promise<InboxView>;
}

export function useInboxViews(workspaceId: string | null): UseInboxViewsResult {
  const [views, setViews] = useState<InboxView[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setViews([]);
      return;
    }
    try {
      setViews(await inboxViewService.list(workspaceId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [workspaceId]);

  useEffect(() => {
    setViews([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    inboxViewService
      .list(workspaceId)
      .then((data) => !cancelled && setViews(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const create = useCallback(
    async (input: CreateInboxViewInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await inboxViewService.create(workspaceId, input);
      await refresh();
      return created;
    },
    [workspaceId, refresh],
  );

  const update = useCallback(
    async (id: string, input: UpdateInboxViewInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await inboxViewService.update(workspaceId, id, input);
      await refresh();
      return updated;
    },
    [workspaceId, refresh],
  );

  return { views, loading, refresh, create, update };
}

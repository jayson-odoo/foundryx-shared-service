'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  quickReplyService,
  type QuickReplyCreateInput,
  type QuickReplyUpdateInput,
} from '@/services/quick-reply-service';
import type { QuickReply } from '@/types/omnichannel';

export interface UseQuickReplies {
  items: QuickReply[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  create: (input: QuickReplyCreateInput) => Promise<QuickReply>;
  update: (id: string, input: QuickReplyUpdateInput) => Promise<QuickReply>;
  remove: (id: string) => Promise<void>;
}

/**
 * Loads + mutates the quick replies for a workspace. The page reads quick
 * replies ONLY through this hook - the UI never touches the service/api-client
 * directly. Idle until a `workspaceId` resolves.
 */
export function useQuickReplies(workspaceId: string | null): UseQuickReplies {
  const [items, setItems] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!workspaceId) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setItems(await quickReplyService.list(workspaceId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load quick replies.');
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = useCallback(
    async (input: QuickReplyCreateInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await quickReplyService.create(workspaceId, input);
      await reload();
      return created;
    },
    [workspaceId, reload],
  );

  const update = useCallback(
    async (id: string, input: QuickReplyUpdateInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await quickReplyService.update(workspaceId, id, input);
      await reload();
      return updated;
    },
    [workspaceId, reload],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      await quickReplyService.remove(workspaceId, id);
      await reload();
    },
    [workspaceId, reload],
  );

  return { items, loading, error, reload, create, update, remove };
}

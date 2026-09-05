'use client';

/**
 * Contact-tag state (plan 25) - backs the workspace Settings -> Tags tab
 * (CRUD) AND the Contact panel's Tags "Add tag" picker (read-only options).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import { contactTagService } from '@/services/contact-tag-service';
import type { ContactTag, CreateContactTagInput, UpdateContactTagInput } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseContactTagsResult {
  tags: ContactTag[];
  loading: boolean;
  refresh: () => Promise<void>;
  create: (input: CreateContactTagInput) => Promise<ContactTag>;
  update: (id: string, input: UpdateContactTagInput) => Promise<ContactTag>;
  remove: (id: string) => Promise<boolean>;
}

export function useContactTags(workspaceId: string | null): UseContactTagsResult {
  const [tags, setTags] = useState<ContactTag[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setTags([]);
      return;
    }
    try {
      setTags(await contactTagService.list(workspaceId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [workspaceId]);

  useEffect(() => {
    // F8 (plan-25 round-3 codex triage): clear immediately on EVERY
    // workspace change (not just to/from null) - otherwise the PREVIOUS
    // workspace's tags stay visible until the new fetch resolves. The
    // `cancelled` flag below already prevents an out-of-order response from
    // clobbering a newer selection.
    setTags([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    contactTagService
      .list(workspaceId)
      .then((data) => !cancelled && setTags(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const create = useCallback(
    async (input: CreateContactTagInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await contactTagService.create(workspaceId, input);
      await refresh();
      return created;
    },
    [workspaceId, refresh],
  );

  const update = useCallback(
    async (id: string, input: UpdateContactTagInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await contactTagService.update(workspaceId, id, input);
      await refresh();
      return updated;
    },
    [workspaceId, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!workspaceId) return false;
      try {
        await contactTagService.remove(workspaceId, id);
        await refresh();
        return true;
      } catch (error) {
        toast.error(describe(error));
        return false;
      }
    },
    [workspaceId, refresh],
  );

  return { tags, loading, refresh, create, update, remove };
}

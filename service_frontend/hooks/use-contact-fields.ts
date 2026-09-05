'use client';

/**
 * Contact-field registry state (plan 25) - backs the workspace Settings ->
 * Contact fields tab (CRUD) AND the Contact panel's Details tab (read-only,
 * to render one typed input per registered field). `refresh()` is exposed so
 * the settings tab can reload after a mutation and the panel can pick up a
 * newly-added field without a full page reload.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { contactFieldService } from '@/services/contact-field-service';
import type { ContactField, CreateContactFieldInput, UpdateContactFieldInput } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseContactFieldsResult {
  fields: ContactField[];
  loading: boolean;
  refresh: () => Promise<void>;
  create: (input: CreateContactFieldInput) => Promise<ContactField>;
  update: (id: string, input: UpdateContactFieldInput) => Promise<ContactField>;
  remove: (id: string) => Promise<boolean>;
}

export function useContactFields(workspaceId: string | null): UseContactFieldsResult {
  const [fields, setFields] = useState<ContactField[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setFields([]);
      return;
    }
    try {
      setFields(await contactFieldService.list(workspaceId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [workspaceId]);

  useEffect(() => {
    // F7 (plan-25 round-3 codex triage): clear immediately on EVERY
    // workspace change (not just to/from null) - otherwise the PREVIOUS
    // workspace's fields stay visible until the new fetch resolves. The
    // `cancelled` flag below already prevents an out-of-order response from
    // clobbering a newer selection.
    setFields([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    contactFieldService
      .list(workspaceId)
      .then((data) => !cancelled && setFields(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const create = useCallback(
    async (input: CreateContactFieldInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await contactFieldService.create(workspaceId, input);
      await refresh();
      return created;
    },
    [workspaceId, refresh],
  );

  const update = useCallback(
    async (id: string, input: UpdateContactFieldInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await contactFieldService.update(workspaceId, id, input);
      await refresh();
      return updated;
    },
    [workspaceId, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!workspaceId) return false;
      try {
        await contactFieldService.remove(workspaceId, id);
        await refresh();
        return true;
      } catch (error) {
        toast.error(describe(error));
        return false;
      }
    },
    [workspaceId, refresh],
  );

  return { fields, loading, refresh, create, update, remove };
}

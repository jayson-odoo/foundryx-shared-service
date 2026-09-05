'use client';

/**
 * Contact-segment state (plan 26) - backs the Contacts list's segment
 * `SearchSelect`, the "Save as segment" dialog and the "Manage segments"
 * dialog. Mirrors `use-contact-tags.ts` / `use-contact-fields.ts` shape.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import { contactSegmentService } from '@/services/contact-segment-service';
import type { ContactSegment, CreateContactSegmentInput, UpdateContactSegmentInput } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseContactSegmentsResult {
  segments: ContactSegment[];
  loading: boolean;
  refresh: () => Promise<void>;
  create: (input: CreateContactSegmentInput) => Promise<ContactSegment>;
  update: (id: string, input: UpdateContactSegmentInput) => Promise<ContactSegment>;
  remove: (id: string) => Promise<boolean>;
}

export function useContactSegments(workspaceId: string | null): UseContactSegmentsResult {
  const [segments, setSegments] = useState<ContactSegment[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setSegments([]);
      return;
    }
    try {
      setSegments(await contactSegmentService.list(workspaceId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [workspaceId]);

  useEffect(() => {
    setSegments([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    contactSegmentService
      .list(workspaceId)
      .then((data) => !cancelled && setSegments(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const create = useCallback(
    async (input: CreateContactSegmentInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const created = await contactSegmentService.create(workspaceId, input);
      await refresh();
      return created;
    },
    [workspaceId, refresh],
  );

  const update = useCallback(
    async (id: string, input: UpdateContactSegmentInput) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      const updated = await contactSegmentService.update(workspaceId, id, input);
      await refresh();
      return updated;
    },
    [workspaceId, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!workspaceId) return false;
      try {
        await contactSegmentService.remove(workspaceId, id);
        await refresh();
        return true;
      } catch (error) {
        toast.error(describe(error));
        return false;
      }
    },
    [workspaceId, refresh],
  );

  return { segments, loading, refresh, create, update, remove };
}

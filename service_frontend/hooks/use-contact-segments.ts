'use client';

/**
 * Contact-segment state (plan 26) - backs the Contacts list's segment
 * `SearchSelect`, the "Save as segment" dialog and the "Manage segments"
 * dialog. Mirrors `use-contact-tags.ts` / `use-contact-fields.ts` shape.
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
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
      // Round-3 fix: do NOT report `loading: false` here. `ContactsPage`
      // only mounts `ResourceList` once its own workspace resolution is
      // `ready` (a SEPARATE hook) - so a caller reading `loading` while
      // `workspaceId` is still null never has a consumer watching it
      // anyway. Reporting `false` here used to create a real race: on the
      // very render where `workspaceId` first goes null -> real id,
      // `ResourceList` mounts in the SAME commit as this effect's dep
      // change fires, but React runs the CHILD's mount effects (the
      // shell's ctx-restored-segment fallback) BEFORE this effect - so the
      // shell read the STALE `loading=false` this branch had already set
      // on the PRIOR (workspaceId=null) render and treated the segment
      // list as final before the real fetch even started, permanently
      // losing a ctx-restored segment. Leaving `loading` at its initial
      // `true` (never toggled false without a real fetch load having
      // completed) removes the false-then-true-again tick entirely.
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

  // Segment delete no longer goes through this hook (review round 2) - it
  // rides the CORE grace-window engine via
  // `use-segment-delete-controller.ts` (`contactSegmentService.remove` stays
  // exported for any future direct-delete caller).

  return { segments, loading, refresh, create, update };
}

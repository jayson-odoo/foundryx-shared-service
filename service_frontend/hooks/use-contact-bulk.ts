'use client';

/**
 * Bulk contact mutations (plan 26, D-A2-5) - Assign / Add tags / Remove tags /
 * Move lifecycle over a selected id set. Each call resolves a `BulkResult`
 * (`{ok, failed}`); `reportBulkResult` renders the ONE toast shape every bulk
 * dialog uses ("N updated", plus the per-record reasons when any failed -
 * never a bare "something went wrong", AC-CTM-09).
 */
import { useCallback, useState } from 'react';
import { toast } from '@/lib/toast';
import { contactService } from '@/services/contact-service';
import type { BulkResult } from '@/types/omnichannel';

export function reportBulkResult(result: BulkResult, verbPast: string): void {
  const okCount = result.ok.length;
  if (result.failed.length === 0) {
    toast.success(`${okCount} contact${okCount === 1 ? '' : 's'} ${verbPast}.`);
    return;
  }
  const reasons = result.failed.map((f) => `${f.id}: ${f.error}`).join('\n');
  if (okCount > 0) {
    toast.warning(`${okCount} ${verbPast}, ${result.failed.length} failed.`, {
      description: reasons,
    });
  } else {
    toast.error(`Could not update ${result.failed.length} contact${result.failed.length === 1 ? '' : 's'}.`, {
      description: reasons,
    });
  }
}

export interface UseContactBulkResult {
  busy: boolean;
  assign: (ids: string[], assigneeUserId: string | null) => Promise<BulkResult>;
  tags: (ids: string[], mode: 'add' | 'remove', tagIds: string[]) => Promise<BulkResult>;
  lifecycle: (ids: string[], toStatusId: string) => Promise<BulkResult>;
}

export function useContactBulk(workspaceId: string | null): UseContactBulkResult {
  const [busy, setBusy] = useState(false);

  const assign = useCallback(
    async (ids: string[], assigneeUserId: string | null) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      setBusy(true);
      try {
        return await contactService.bulkAssign(workspaceId, { ids, assigneeUserId });
      } finally {
        setBusy(false);
      }
    },
    [workspaceId],
  );

  const tags = useCallback(
    async (ids: string[], mode: 'add' | 'remove', tagIds: string[]) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      setBusy(true);
      try {
        return await contactService.bulkTags(workspaceId, { ids, mode, tagIds });
      } finally {
        setBusy(false);
      }
    },
    [workspaceId],
  );

  const lifecycle = useCallback(
    async (ids: string[], toStatusId: string) => {
      if (!workspaceId) throw new Error('No workspace selected.');
      setBusy(true);
      try {
        return await contactService.bulkLifecycle(workspaceId, { ids, toStatusId });
      } finally {
        setBusy(false);
      }
    },
    [workspaceId],
  );

  return { busy, assign, tags, lifecycle };
}

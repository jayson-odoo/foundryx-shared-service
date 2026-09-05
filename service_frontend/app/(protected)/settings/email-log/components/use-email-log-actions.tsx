'use client';

import { useMemo } from 'react';
import { Ban, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { emailLogService } from '@/services/email-log-service';
import type { EmailLogListItem } from '@/types/templates';

/** Retry + Cancel (D14) - one registry for row `…`, bulk and detail `…`. */
export function useEmailLogActions(): ResourceAction<EmailLogListItem>[] {
  return useMemo<ResourceAction<EmailLogListItem>[]>(
    () => [
      {
        id: 'retry',
        label: 'Retry',
        icon: RotateCcw,
        surfaces: { row: true, bulk: true, form: true },
        permission: 'emails.manage',
        isVisible: (rows) => rows.every((r) => r.status === 'FAILED' || r.status === 'CANCELLED'),
        run: async (rows, runtime) => {
          for (const row of rows) {
            await emailLogService.retry(row.id);
          }
          toast.success(`Queued ${rows.length} email(s) for retry.`);
          runtime.reload();
        },
      },
      {
        id: 'cancel',
        label: 'Cancel',
        icon: Ban,
        tone: 'destructive',
        surfaces: { row: true, bulk: true, form: true },
        permission: 'emails.manage',
        isVisible: (rows) => rows.every((r) => r.status === 'PENDING'),
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `email_outbox.cancel`
        // handler commits it server-side; a cancelled email stays retryable,
        // so this is the reversible window - matching D14's "cancelled rows
        // retryable" contract).
        deferred: { actionKey: 'email_outbox.cancel', entityType: 'email_outbox' },
      },
    ],
    [],
  );
}

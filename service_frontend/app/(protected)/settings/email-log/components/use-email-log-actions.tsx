'use client';

import { useMemo } from 'react';
import { Ban, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { emailLogService } from '@/services/email-log-service';
import type { EmailLogListItem } from '@/types/templates';

/** Retry + Cancel (D14) — one registry for row `…`, bulk and detail `…`. */
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
        confirm: {
          title: 'Cancel pending email?',
          description:
            'The email will not be sent. If the dispatcher already claimed it, cancelling fails — it was too late.',
          confirmLabel: 'Cancel email',
        },
        run: async (rows, runtime) => {
          let cancelled = 0;
          for (const row of rows) {
            try {
              await emailLogService.cancel(row.id);
              cancelled += 1;
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Cancel failed.');
            }
          }
          if (cancelled) toast.success(`Cancelled ${cancelled} email(s).`);
          runtime.reload();
        },
      },
    ],
    [],
  );
}

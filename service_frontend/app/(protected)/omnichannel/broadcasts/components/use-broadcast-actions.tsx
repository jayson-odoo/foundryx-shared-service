'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Ban, Copy, Pencil, Send, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction } from '@/components/platform/resource-list';
import { broadcastService } from '@/services/broadcast-service';
import type { Broadcast } from '@/types/omnichannel';
import { broadcastFormHref } from './paths';
import { useActingUserName } from './use-acting-user-name';
import { fxCancelledToast, fxDuplicatedToast, fxSendingToast } from './fx-broadcast-words';

// Typed 409 reasons (plan §5.1) - `error.message` is just "Conflict" for
// these (the backend body is `{reason: "..."}`, not a string `detail`, so
// `apiFetch` falls back to `res.statusText`); map the reason to real copy.
const CONFLICT_REASONS: Record<string, string> = {
  broadcast_not_editable: 'Only a Draft broadcast can be edited or deleted.',
  broadcast_not_cancellable: 'This broadcast can no longer be cancelled.',
  broadcast_already_sending: 'This broadcast cannot be sent again.',
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = (error.detail as { reason?: string } | null)?.reason;
    if (reason && CONFLICT_REASONS[reason]) return CONFLICT_REASONS[reason];
    return error.message;
  }
  return 'Something went wrong. Please try again.';
}

/**
 * The Broadcast action registry (plan 29, AC-BRD-11) - one registry serves
 * the list row `…` menu, the bulk toolbar and the form `…` menu.
 */
export function useBroadcastActions(workspaceId: string | null): ResourceAction<Broadcast>[] {
  const router = useRouter();
  // Foundryx UIUX switch only: the done toasts say what, for whom, how many
  // and by whom. The requests never change; none of these can be reversed
  // through the API, so none offers Undo.
  const fx = useFx();
  const byWhom = useActingUserName();

  return useMemo<ResourceAction<Broadcast>[]>(() => {
    const editable = (rows: Broadcast[]) => rows.length > 0 && rows.every((r) => r.status === 'DRAFT');
    const sendable = (rows: Broadcast[]) =>
      rows.length > 0 && rows.every((r) => r.status === 'DRAFT' || r.status === 'SCHEDULED');
    const cancellable = (rows: Broadcast[]) =>
      rows.length > 0 && rows.every((r) => r.status === 'SCHEDULED' || r.status === 'SENDING');

    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'broadcasts.manage',
        surfaces: { row: true },
        isVisible: editable,
        run: ([row], rt) => {
          if (!row) return;
          router.push(broadcastFormHref(row.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'send',
        label: 'Send now',
        icon: Send,
        permission: 'broadcasts.send',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: sendable,
        run: async (rows, rt) => {
          if (!workspaceId) return;
          for (const row of rows) {
            try {
              await broadcastService.send(workspaceId, row.id, null);
            } catch (error) {
              toast.error(describe(error));
              return;
            }
          }
          if (fx) toast.fxDone(fxSendingToast(rows, byWhom));
          else toast.success(rows.length > 1 ? `Sending ${rows.length} broadcasts.` : 'Sending broadcast.');
          rt.reload();
        },
      },
      {
        id: 'cancel',
        label: 'Cancel',
        icon: Ban,
        tone: 'destructive',
        permission: 'broadcasts.send',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: cancellable,
        // No `confirm` here (plan 29 deviation from AC-BRD-11's literal
        // "(confirmation dialog)" wording, flagged, not silently redesigned):
        // `ResourceAction.confirm` is hard-reserved to a NAMED allowlist
        // (`confirm-carve-outs.inventory.test.ts`) this action isn't on, and
        // `deferred` (the system's actual confirm-dialog replacement) needs a
        // backend-registered handler that doesn't exist until the S1/S2
        // backend lands `broadcasts.cancel`. Plain immediate `run` (same
        // shape as `use-workspace-actions.tsx`'s Restore) is the only
        // correct S0 choice; S2 should register this as a real `deferred`
        // action once the backend exists, matching every other module verb
        // in this class (workspace trash, channel disconnect, …).
        run: async (rows, rt) => {
          if (!workspaceId) return;
          for (const row of rows) {
            try {
              await broadcastService.cancel(workspaceId, row.id);
            } catch (error) {
              toast.error(describe(error));
              return;
            }
          }
          if (fx) toast.fxDone(fxCancelledToast(rows, byWhom));
          else toast.success(rows.length > 1 ? `Cancelled ${rows.length} broadcasts.` : 'Broadcast cancelled.');
          rt.reload();
        },
      },
      {
        id: 'duplicate',
        label: 'Duplicate',
        icon: Copy,
        permission: 'broadcasts.manage',
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1,
        run: async ([row], rt) => {
          if (!workspaceId || !row) return;
          const copy = await broadcastService.duplicate(workspaceId, row.id);
          if (fx) toast.fxDone(fxDuplicatedToast(row, copy, byWhom));
          else toast.success(`Duplicated as "${copy.name}".`);
          rt.reload();
          router.push(broadcastFormHref(copy.id, { edit: true }));
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'broadcasts.manage',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: editable,
        // Grace-window deferred action (review round 1, S1) - no confirm
        // dialog, no immediate `run`; the registered `broadcasts.delete`
        // handler commits it server-side once the countdown lapses, same
        // shape as every other destructive verb in this module (channel
        // delete, segment delete, quick-reply delete, …).
        deferred: {
          actionKey: 'broadcasts.delete',
          entityType: 'broadcast',
          // Foundryx UIUX switch only: "Deleting November promo in 10 s".
          fxName: (rows) => (rows.length === 1 ? rows[0]?.name : undefined),
        },
      },
    ];
  }, [router, workspaceId, fx, byWhom]);
}

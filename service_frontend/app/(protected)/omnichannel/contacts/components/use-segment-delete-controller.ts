'use client';

/**
 * Segment delete controller (plan 26, review round 2 - blocker 2 + should-fix
 * 4). Owns the ONE `useDeferredAction` instance for "Manage segments" row
 * deletes.
 *
 * Round-1 shipped this logic INSIDE `ManageSegmentsDialog`. Two bugs followed
 * from that:
 *   - blocker 2: a single hook instance shared across every row meant
 *     deleting segment A then segment B (while A was still counting down)
 *     overwrote the hook's internal parked state - A's own Cancel silently
 *     cancelled B instead, and A's toast was orphaned (no `onCommitted` ever
 *     fired for it).
 *   - should-fix 4: `ManageSegmentsDialog`'s own `<DialogContent>` children
 *     unmount when the dialog closes (Radix `Presence` + this app's
 *     `AnimatePresence` wrapper) - a controller that instead lived on a
 *     PER-ROW component nested in there would stop polling the instant the
 *     dialog closed, stranding a live countdown with no `onCommitted`/list
 *     refresh.
 *
 * Fix: ONE controller, lifted onto the PAGE (`page.tsx` mounts this, not the
 * dialog) so it survives the dialog opening/closing entirely, combined with
 * "one delete at a time" (the dialog disables every row's Delete button
 * while `deletingId` is set) - the exact race blocker 2 depends on (two
 * concurrent parks under one hook) can no longer happen, and the countdown
 * keeps polling/toasting/refreshing regardless of the dialog's open state.
 */
import { useCallback, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import { deferredToast, dismissDeferredToast } from '@/components/platform/resource-actions/deferred-toast';
import type { ContactSegment } from '@/types/omnichannel';

const DELETE_LABEL = 'Delete';
const ENTITY_TYPE = 'contact_segment';

export function toastIdForSegment(segmentId: string): string {
  return `contact-segment-delete-${segmentId}`;
}

export interface SegmentDeleteController {
  /** The segment currently parked for delete, or null - the dialog disables
   * every OTHER row's Delete button while this is set (one countdown at a
   * time, matching the engine's model). */
  deletingId: string | null;
  startDelete: (segment: ContactSegment) => Promise<void>;
}

export function useSegmentDeleteController(onDeleted?: () => void): SegmentDeleteController {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Read from callbacks that outlive any single render (mirrors ActionMenu's
  // own `activeRef`).
  const activeRef = useRef<{ id: string } | null>(null);
  // Round-3 fix: `activeRef` is set only AFTER `await deferred.start(...)`
  // resolves, so two `startDelete` calls in the same tick (e.g. a fast
  // double-invoke on the row button) both read `activeRef.current === null`
  // and both start a park under the SAME hook instance. Set `startingRef`
  // SYNCHRONOUSLY before the await so the second call's guard check sees it
  // immediately; cleared once the in-flight call settles (either `activeRef`
  // takes over on success, or the catch runs on failure) so a later,
  // legitimate `startDelete` is never permanently blocked.
  const startingRef = useRef(false);

  const settleDelete = useCallback(() => {
    const active = activeRef.current;
    activeRef.current = null;
    if (active) dismissDeferredToast(toastIdForSegment(active.id));
    setDeletingId(null);
  }, []);

  const deferred = useDeferredAction({
    onCommitted: () => {
      settleDelete();
      toast.success(deferredDoneMessage(DELETE_LABEL, ENTITY_TYPE, 1));
      onDeleted?.();
    },
    onFailed: (error) => {
      settleDelete();
      toast.error(error || 'Could not delete the segment.');
    },
    onCancelledElsewhere: settleDelete,
  });

  const startDelete = useCallback(
    async (segment: ContactSegment) => {
      // Defensive: the dialog already disables every row's Delete button
      // while one is pending - this guards the controller itself against a
      // stray second call (e.g. a fast double-invoke) ever starting a
      // concurrent park under the SAME hook instance. `startingRef` is the
      // SYNCHRONOUS half of the guard (set before the first `await`); a
      // second call arriving in the same tick - before `activeRef` is set -
      // is a no-op too.
      if (activeRef.current || startingRef.current) return;
      startingRef.current = true;
      setDeletingId(segment.id);
      try {
        const { commitAt, windowSeconds } = await deferred.start('contact_segments.delete', {
          entityType: ENTITY_TYPE,
          entityId: segment.id,
        });
        activeRef.current = { id: segment.id };
        deferredToast({
          id: toastIdForSegment(segment.id),
          verb: presentContinuous(DELETE_LABEL),
          commitAt,
          windowSeconds,
          onCancel: () => {
            void deferred.cancel();
            settleDelete();
          },
        });
      } catch (error) {
        setDeletingId(null);
        toast.error(error instanceof Error ? error.message : 'Could not delete the segment.');
      } finally {
        startingRef.current = false;
      }
    },
    [deferred, settleDelete],
  );

  return { deletingId, startDelete };
}

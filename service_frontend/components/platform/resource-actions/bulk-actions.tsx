'use client';

import { useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { useCan } from '@/hooks/use-can';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { deferredDoneMessage, entityNoun, presentContinuous } from '@/lib/deferred-verb';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  trackPendingEntities,
  untrackPendingEntities,
} from '@/lib/pending-entity-store';
import type {
  ResourceAction,
  ResourceActionRuntime,
} from '@/components/platform/resource-list/types';
import { ConfirmActionDialog } from './confirm-action-dialog';
import { deferredToast, dismissDeferredToast } from './deferred-toast';

export interface BulkActionsProps<T> {
  actions: ResourceAction<T>[];
  rows: T[];
  runtime: ResourceActionRuntime;
  /** Row id extractor for a `deferred` action's park - defaults to `row.id`. */
  getEntityId?: (row: T) => string;
}

function defaultEntityId<T>(row: T): string {
  return String((row as { id?: unknown }).id ?? '');
}

/**
 * Bulk toolbar as a single dropdown (plan 02 review) - scales as more bulk
 * actions are added per list. Typed-confirmation actions route through
 * `ConfirmActionDialog` (module uninstall / tenant purge ONLY); every other
 * destructive/reversible bulk action parks ONE deferred row per selected
 * record behind a SINGLE countdown naming the count (D13, AC-DLA-45).
 */
export function BulkActions<T>({
  actions,
  rows,
  runtime,
  getEntityId = defaultEntityId,
}: BulkActionsProps<T>) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ResourceAction<T> | null>(null);
  const { can } = useCan();

  const activeRef = useRef<{
    ids: string[];
    toastId: string | number;
    label: string;
    entityType: string;
  } | null>(null);
  const settleActive = () => {
    const active = activeRef.current;
    if (active) {
      untrackPendingEntities(active.ids);
      dismissDeferredToast(active.toastId);
    }
    activeRef.current = null;
    return active;
  };
  const deferred = useDeferredAction({
    onCommitted: () => {
      const active = settleActive();
      toast.success(
        active ? deferredDoneMessage(active.label, active.entityType, active.ids.length) : 'Done.',
      );
      runtime.reload();
    },
    onFailed: (error) => {
      settleActive();
      toast.error(error || 'The action failed.');
    },
    onCancelledElsewhere: () => {
      settleActive();
    },
  });

  const visible = actions.filter(
    (a) =>
      a.surfaces.bulk &&
      (!a.permission || can(a.permission)) &&
      (a.isVisible ? a.isVisible(rows) : true),
  );
  if (!visible.length) return null;

  async function run(action: ResourceAction<T>) {
    if (action.deferred) {
      const entityIds = rows.map(getEntityId);
      const label = typeof action.label === 'function' ? action.label(rows) : action.label;
      const entityType = action.deferred.entityType;
      trackPendingEntities(entityIds);
      try {
        const { commitAt, windowSeconds, failedCount, parkedEntityIds: parkedIds } =
          await deferred.start(
            action.deferred.actionKey,
            entityIds.map((id) => ({ entityType, entityId: id })),
          );
        untrackPendingEntities(entityIds.filter((id) => !parkedIds.includes(id)));
        const toastId = `pending-action-bulk-${Date.now()}`;
        activeRef.current = { ids: parkedIds, toastId, label, entityType };
        deferredToast({
          id: toastId,
          verb: presentContinuous(label),
          commitAt,
          windowSeconds,
          count: parkedIds.length > 1 ? parkedIds.length : undefined,
          noun: entityNoun(entityType, parkedIds.length),
          onCancel: () => {
            void deferred.cancel();
            untrackPendingEntities(parkedIds);
            dismissDeferredToast(toastId);
            activeRef.current = null;
          },
        });
        if (failedCount > 0) {
          // Fix round 1 item 3: `start()` used `Promise.allSettled` - the
          // rows that DID park stay tracked above; ONE toast names the rest.
          toast.error(
            `Could not start "${label}" on ${failedCount} of ${entityIds.length} - another action may already be pending on ${failedCount === 1 ? 'it' : 'them'}.`,
          );
        }
      } catch (error) {
        untrackPendingEntities(entityIds);
        toast.error(error instanceof Error ? error.message : 'Could not start that action.');
      }
      return;
    }
    await action.run(rows, runtime);
  }

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          {/* aria-label disambiguates from the per-row "Actions" buttons. */}
          <Button variant="outline" size="sm" aria-label="Bulk actions">
            Actions
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {visible.map((action) => {
            const Icon = action.icon;
            return (
              <DropdownMenuItem
                key={action.id}
                disabled={action.isDisabled ? action.isDisabled(rows) : false}
                variant={
                  action.tone === 'destructive' ? 'destructive' : undefined
                }
                onSelect={(e) => {
                  // Same contract as ActionMenu: preventDefault avoids the
                  // Radix dialog race, the explicit close keeps the menu's
                  // overlay from swallowing later clicks (review finding).
                  e.preventDefault();
                  setOpen(false);
                  if (action.confirm) setPending(action);
                  else void run(action);
                }}
              >
                {Icon && <Icon />}
                {typeof action.label === 'function' ? action.label(rows) : action.label}
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmActionDialog
        pending={pending}
        rows={rows}
        onClose={() => setPending(null)}
        onConfirm={(action) => void run(action)}
      />
    </>
  );
}

'use client';

import { Fragment, useRef, useState } from 'react';
import { MoreHorizontal, Settings2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { useCan } from '@/hooks/use-can';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { deferredDoneMessage, entityNoun, presentContinuous } from '@/lib/deferred-verb';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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

export interface ActionMenuProps<T> {
  actions: ResourceAction<T>[];
  rows: T[];
  runtime: ResourceActionRuntime;
  surface: 'row' | 'form';
  /**
   * `'dots'` (default, omit or pass explicitly) renders the "…" icon button;
   * `'gear'` renders the record-card gear icon (D5) instead. Pass a custom
   * `React.ReactElement` for anything else. Narrowed from a bare
   * `React.ReactNode | 'gear'` (fix round 1, nit) - a literal `ReactNode`
   * union with a string variant lets a plain text trigger silently collide
   * with the 'gear' sentinel (e.g. a future `trigger="gear icon"` typo would
   * have rendered as a raw text node, not thrown).
   */
  trigger?: 'gear' | 'dots' | React.ReactElement;
  align?: 'start' | 'end';
  /**
   * Row id extractor for a `deferred` action's park (sprint-4/23, T5) -
   * defaults to `row.id` (every entity in this codebase has one).
   */
  getEntityId?: (row: T) => string;
  /**
   * Lets the FORM surface lift a deferred action's countdown into the record
   * card's primary area (AC-DLA-44) instead of this component's own toast -
   * `resource-form.tsx` passes this; the row surface leaves it unset and
   * gets the self-contained toast (AC-DLA-45).
   */
  onDeferredStart?: (
    action: ResourceAction<T>,
    entityIds: string[],
  ) => void;
  /**
   * Called after a self-contained (row-surface) deferred action actually
   * COMMITS - alongside the generic toast + `runtime.reload()`, never
   * instead of them (fix round 1, T5, item 15). For a caller that needs to
   * react beyond a list refresh (e.g. bumping a sibling "reload" token so
   * ANOTHER surface re-seeds after this one's commit).
   */
  onDeferredCommitted?: (action: ResourceAction<T>, entityIds: string[]) => void;
}

/**
 * Secondary actions first (declaration order preserved), then a separator,
 * then `tone: 'destructive'` actions last (D5/AC-DLA-28) - applies on every
 * surface (row, bulk, form) so a destructive action never sits ahead of a
 * safe one in any "…" menu.
 */
function orderActions<T>(actions: ResourceAction<T>[]): ResourceAction<T>[] {
  const secondary = actions.filter((a) => a.tone !== 'destructive');
  const destructive = actions.filter((a) => a.tone === 'destructive');
  return [...secondary, ...destructive];
}

function defaultEntityId<T>(row: T): string {
  return String((row as { id?: unknown }).id ?? '');
}

/**
 * Renders an entity's action registry as a "…" menu, for the row and form
 * surfaces (plan 02 §3c). Typed-confirmation actions route through the
 * shared `ConfirmActionDialog` (module uninstall / tenant purge ONLY,
 * AC-DLA-47); every other destructive/reversible action carries `deferred`
 * and runs through `useDeferredAction` instead (D2, AC-DLA-43) - no confirm
 * dialog, a grace-window countdown in its place.
 */
export function ActionMenu<T>({
  actions,
  rows,
  runtime,
  surface,
  trigger,
  align = 'end',
  getEntityId = defaultEntityId,
  onDeferredStart,
  onDeferredCommitted,
}: ActionMenuProps<T>) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ResourceAction<T> | null>(null);
  const { can } = useCan();

  const activeRef = useRef<{
    ids: string[];
    toastId: string | number;
    label: string;
    entityType: string;
    action: ResourceAction<T>;
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
      if (active) onDeferredCommitted?.(active.action, active.ids);
    },
    onFailed: (error) => {
      settleActive();
      toast.error(error || 'The action failed.');
    },
    onCancelledElsewhere: () => {
      // A teammate cancelled this SAME action from another tab/session
      // (fix round 1 item 1/2) - reconcile our own toast/dim WITHOUT
      // treating it as a success.
      settleActive();
    },
  });

  const visible = orderActions(
    actions.filter(
      (a) =>
        a.surfaces[surface] &&
        (!a.permission || can(a.permission)) &&
        (a.isVisible ? a.isVisible(rows) : true),
    ),
  );
  if (!visible.length) return null;

  // The separator sits once, right before the first destructive item (the
  // ordering above already grouped them last).
  const firstDestructiveIndex = visible.findIndex(
    (a) => a.tone === 'destructive',
  );

  async function run(action: ResourceAction<T>) {
    if (action.deferred) {
      const entityIds = rows.map(getEntityId);
      if (surface === 'form' && onDeferredStart) {
        onDeferredStart(action, entityIds);
        return;
      }
      const label = typeof action.label === 'function' ? action.label(rows) : action.label;
      const entityType = action.deferred.entityType;
      trackPendingEntities(entityIds);
      try {
        const { commitAt, windowSeconds, failedCount, parkedEntityIds: parkedIds } =
          await deferred.start(
            action.deferred.actionKey,
            entityIds.map((id) => ({ entityType, entityId: id })),
            action.deferred.payload?.(rows),
          );
        untrackPendingEntities(entityIds.filter((id) => !parkedIds.includes(id)));
        const toastId = `pending-action-${entityIds[0]}`;
        activeRef.current = { ids: parkedIds, toastId, label, entityType, action };
        deferredToast({
          id: toastId,
          verb: presentContinuous(label),
          commitAt,
          windowSeconds,
          count: parkedIds.length > 1 ? parkedIds.length : undefined,
          noun: parkedIds.length > 1 ? entityNoun(entityType, parkedIds.length) : undefined,
          onCancel: () => {
            void deferred.cancel();
            untrackPendingEntities(parkedIds);
            dismissDeferredToast(toastId);
            activeRef.current = null;
          },
        });
        if (failedCount > 0) {
          // Fix round 1 item 3: the parks that succeeded stay tracked above;
          // ONE toast names how many could not be started.
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
          {trigger === 'gear' ? (
            <Button
              variant="outline"
              size="sm"
              mode="icon"
              aria-label="Actions"
            >
              <Settings2 />
            </Button>
          ) : trigger && trigger !== 'dots' ? (
            trigger
          ) : (
            <Button variant="ghost" size="sm" mode="icon" aria-label="Actions">
              <MoreHorizontal />
            </Button>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align={align} className="w-48">
          {visible.map((action, index) => {
            const Icon = action.icon;
            const disabled = action.isDisabled
              ? action.isDisabled(rows)
              : false;
            return (
              <Fragment key={action.id}>
                {index === firstDestructiveIndex &&
                  firstDestructiveIndex > 0 && <DropdownMenuSeparator />}
                <DropdownMenuItem
                  disabled={disabled}
                  variant={
                    action.tone === 'destructive' ? 'destructive' : undefined
                  }
                  onSelect={(e) => {
                    // preventDefault keeps Radix from auto-closing (which races
                    // dialogs opened by the action); we close EXPLICITLY instead
                    // - a menu left open intercepts every later click on the
                    // page (the change-email banner bug, plan 06 review).
                    e.preventDefault();
                    setOpen(false);
                    if (action.confirm) setPending(action);
                    else void run(action);
                  }}
                >
                  {Icon && <Icon />}
                  {typeof action.label === 'function'
                    ? action.label(rows)
                    : action.label}
                </DropdownMenuItem>
              </Fragment>
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

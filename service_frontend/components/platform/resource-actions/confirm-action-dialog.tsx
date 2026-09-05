'use client';

/**
 * ONE confirm dialog for the action registry (code-review consolidation -
 * was duplicated verbatim in action-menu and bulk-actions).
 *
 * **RESERVED for the disclosed confirm carve-outs (sprint-4/23, T5,
 * D2/D13/AC-DLA-43/47) - every other destructive/reversible action in the
 * app uses `ResourceAction.deferred` instead (the grace-window engine,
 * `hooks/use-deferred-action.ts`) - no confirm dialog, a countdown with
 * Cancel in its place.** `confirm-carve-outs.inventory.test.ts` is the
 * SINGLE SOURCE OF TRUTH for exactly which files/blocks may still define
 * `ResourceAction.confirm` - read it before adding a new one.
 *
 * As of T5 fix round 2 there are FOUR typed (`confirm.input`) carve-out
 * sites across three files:
 * - `components/platform/app-store/use-module-list-config.tsx` - module
 *   uninstall.
 * - `app/(protected)/platform/tenants/components/use-tenant-actions.tsx` -
 *   tenant purge (irreversible hard delete): a single row types the tenant's
 *   slug, a bulk selection types `DELETE` - two separate typed sites in the
 *   one file.
 * - `app/(protected)/documents/shares/page.tsx` - Documents > Shares BULK
 *   revoke only (T5 fix round 2, S1: a shipped sprint-3/05 UAT criterion,
 *   AC-OVERSIGHT-03/AC-UX-03 - the ROW-surface revoke on that same page
 *   stays on `deferred`).
 *
 * PLAIN (non-typed) `confirm` exceptions are listed ONLY in
 * `DISCLOSED_PLAIN_CONFIRMS` inside `confirm-carve-outs.inventory.test.ts`
 * (currently: Users' "Impersonate" - a session action with no sensible
 * grace-window commit semantics; the tenant custom-status-edge fallback -
 * an operator-added custom status sharing a well-known label but a
 * different key, BL-SS-052; and the operator-console module Deactivate -
 * a cross-tenant action outside the deferred-actions engine's own-tenant
 * scope). Do not re-list them here - that inventory test is what actually
 * fails loudly if this drifts; a comment can't enforce anything on its own.
 *
 * Supports the typed-confirmation contract (`confirm.input`): the confirm
 * button stays disabled until the user types `expected(rows)` exactly -
 * renders on the lightbox spring via `AlertDialog` (T3).
 */
import { useState } from 'react';
import { cn } from '@/lib/utils';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Input } from '@/components/ui/input';
import type { ResourceAction } from '@/components/platform/resource-list/types';

export interface ConfirmActionDialogProps<T> {
  /** The action awaiting confirmation - null renders the dialog closed. */
  pending: ResourceAction<T> | null;
  rows: T[];
  onClose: () => void;
  onConfirm: (action: ResourceAction<T>) => void;
}

export function ConfirmActionDialog<T>({
  pending,
  rows,
  onClose,
  onConfirm,
}: ConfirmActionDialogProps<T>) {
  // Typed confirmation (irreversible actions) - must match expected exactly.
  const [confirmText, setConfirmText] = useState('');

  const close = () => {
    setConfirmText('');
    onClose();
  };

  return (
    <AlertDialog
      open={Boolean(pending)}
      onOpenChange={(open) => !open && close()}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{pending?.confirm?.title}</AlertDialogTitle>
          {pending?.confirm?.description && (
            <AlertDialogDescription>
              {pending.confirm.description}
            </AlertDialogDescription>
          )}
        </AlertDialogHeader>
        {pending?.confirm?.input && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs text-muted-foreground">
              {pending.confirm.input.hint?.(rows) ??
                `Type "${pending.confirm.input.expected(rows)}" to confirm.`}
            </p>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={pending.confirm.input.expected(rows)}
              aria-label="Confirmation text"
            />
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={cn(
              pending?.tone === 'destructive' &&
                'bg-destructive text-destructive-foreground hover:bg-destructive/90',
            )}
            disabled={
              Boolean(pending?.confirm?.input) &&
              confirmText !== pending?.confirm?.input?.expected(rows)
            }
            onClick={() => {
              if (pending) onConfirm(pending);
              close();
            }}
          >
            {pending?.confirm?.confirmLabel ?? 'Confirm'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

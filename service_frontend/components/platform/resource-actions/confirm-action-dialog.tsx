'use client';

/**
 * ONE confirm dialog for the action registry (code-review consolidation -
 * was duplicated verbatim in action-menu and bulk-actions).
 *
 * **RESERVED for the two typed-confirmation carve-outs (sprint-4/23, T5,
 * D2/D13/AC-DLA-43/47) - the ONLY allowed importers of `ResourceAction.confirm`
 * are `components/platform/app-store/use-module-list-config.tsx` (module
 * uninstall) and `app/(protected)/platform/tenants/components/
 * use-tenant-actions.tsx` (tenant purge, irreversible hard delete).** Every
 * other destructive/reversible action in the app uses `ResourceAction.deferred`
 * instead (the grace-window engine, `hooks/use-deferred-action.ts`) - no
 * confirm dialog, a countdown with Cancel in its place. `confirm-carve-outs.
 * inventory.test.ts` pins this to exactly those two files, PLUS one disclosed
 * third exception (Users' "Impersonate" - a session action with no sensible
 * grace-window commit semantics; see the T5 report).
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

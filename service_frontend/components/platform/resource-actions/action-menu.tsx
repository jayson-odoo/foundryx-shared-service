'use client';

import { useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { useCan } from '@/hooks/use-can';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type {
  ResourceAction,
  ResourceActionRuntime,
} from '@/components/platform/resource-list/types';
import { ConfirmActionDialog } from './confirm-action-dialog';

export interface ActionMenuProps<T> {
  actions: ResourceAction<T>[];
  rows: T[];
  runtime: ResourceActionRuntime;
  surface: 'row' | 'form';
  /** Custom trigger; defaults to a "…" icon button. */
  trigger?: React.ReactNode;
  align?: 'start' | 'end';
}

/**
 * Renders an entity's action registry as a "…" menu, for the row and form
 * surfaces (plan 02 §3c). Confirmable actions route through the shared
 * ConfirmActionDialog (typed-confirmation supported).
 */
export function ActionMenu<T>({
  actions,
  rows,
  runtime,
  surface,
  trigger,
  align = 'end',
}: ActionMenuProps<T>) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ResourceAction<T> | null>(null);
  const { can } = useCan();

  const visible = actions.filter(
    (a) =>
      a.surfaces[surface] &&
      (!a.permission || can(a.permission)) &&
      (a.isVisible ? a.isVisible(rows) : true),
  );
  if (!visible.length) return null;

  async function run(action: ResourceAction<T>) {
    await action.run(rows, runtime);
  }

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          {trigger ?? (
            <Button variant="ghost" size="sm" mode="icon" aria-label="Actions">
              <MoreHorizontal />
            </Button>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align={align} className="w-48">
          {visible.map((action) => {
            const Icon = action.icon;
            const disabled = action.isDisabled
              ? action.isDisabled(rows)
              : false;
            return (
              <DropdownMenuItem
                key={action.id}
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

'use client';

import { Fragment, useState } from 'react';
import { MoreHorizontal, Settings2 } from 'lucide-react';
import { useCan } from '@/hooks/use-can';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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

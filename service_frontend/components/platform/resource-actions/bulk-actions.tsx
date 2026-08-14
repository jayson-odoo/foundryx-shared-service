'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
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

export interface BulkActionsProps<T> {
  actions: ResourceAction<T>[];
  rows: T[];
  runtime: ResourceActionRuntime;
}

/**
 * Bulk toolbar as a single dropdown (plan 02 review) - scales as more bulk
 * actions are added per list. Confirmable actions route through the shared
 * ConfirmActionDialog (typed-confirmation supported).
 */
export function BulkActions<T>({
  actions,
  rows,
  runtime,
}: BulkActionsProps<T>) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ResourceAction<T> | null>(null);
  const { can } = useCan();

  const visible = actions.filter(
    (a) =>
      a.surfaces.bulk &&
      (!a.permission || can(a.permission)) &&
      (a.isVisible ? a.isVisible(rows) : true),
  );
  if (!visible.length) return null;

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
                  else void action.run(rows, runtime);
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
        onConfirm={(action) => void action.run(rows, runtime)}
      />
    </>
  );
}

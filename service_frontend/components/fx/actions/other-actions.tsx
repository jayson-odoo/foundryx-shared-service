'use client';

/**
 * The Other Actions row (playbook 0.71.0 "Several actions on one page become
 * one Main Action and Other Actions"): icon actions left of the red action,
 * in order of use. Past four, the rest go in a More (three dots) menu, where
 * they keep their words.
 */
import { useState } from 'react';
import { cn } from '@/lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { FxIcon } from '@/components/fx/icons';
import { FxIconAction, FxIconActionButton } from './icon-action';
import type { FxOtherActionSpec } from './page-actions-context';

/** How many icons show before the More menu takes the rest. */
export const FX_MAX_ICON_ACTIONS = 4;

/** Splits actions into the shown icons and the More menu (pure). */
export function splitOtherActions<A>(
  actions: A[],
  max = FX_MAX_ICON_ACTIONS,
): { shown: A[]; more: A[] } {
  if (actions.length <= max) return { shown: actions, more: [] };
  return { shown: actions.slice(0, max), more: actions.slice(max) };
}

interface FxOtherActionsProps {
  actions: FxOtherActionSpec[];
  /** Ids that always go in More, whatever the count (page config). */
  moreIds?: string[];
  className?: string;
}

export function FxOtherActions({
  actions,
  moreIds = [],
  className,
}: FxOtherActionsProps) {
  const [open, setOpen] = useState(false);
  const forced = actions.filter((a) => moreIds.includes(a.id));
  const split = splitOtherActions(actions.filter((a) => !moreIds.includes(a.id)));
  const shown = split.shown;
  const more = [...split.more, ...forced];
  if (!shown.length && !more.length) return null;

  return (
    <div
      data-fx-other-actions=""
      className={cn('flex flex-nowrap items-center gap-2', className)}
    >
      {shown.map((action) => (
        <FxIconAction
          key={action.id}
          label={action.label}
          icon={action.icon}
          tone={action.tone}
          disabledReason={action.disabledReason}
          onClick={action.onClick}
        />
      ))}
      {more.length > 0 && (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <FxTooltip label="More">
            <DropdownMenuTrigger asChild>
              <FxIconActionButton label="More" icon="more" />
            </DropdownMenuTrigger>
          </FxTooltip>
          <DropdownMenuContent
            align="end"
            className="rounded-(--fx-r-m) border-(--fx-line) bg-(--fx-surface) text-(--fx-ink)"
          >
            {more.map((action) => (
              <DropdownMenuItem
                key={action.id}
                disabled={Boolean(action.disabledReason)}
                title={action.disabledReason}
                className={cn(
                  'gap-2',
                  action.tone === 'delete' && 'text-(--fx-act)',
                )}
                onSelect={(event) => {
                  event.preventDefault();
                  setOpen(false);
                  action.onClick();
                }}
              >
                <FxIcon name={action.icon} size={16} />
                {action.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

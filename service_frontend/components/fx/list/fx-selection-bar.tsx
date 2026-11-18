'use client';

/**
 * The selection bar (playbook 0.71.0 "Lists > Acting on ticked rows").
 *
 * Once a row is ticked it slides in over the list's filter bar (0.2 s)
 * without moving the rows: "3 selected", "Select all 312" (every match, past
 * the loaded page), the bulk actions as Other Action icon buttons, Export,
 * and an × that clears the ticks. An action that cannot apply to every
 * ticked row is greyed with its reason as the tooltip. On phones it floats
 * at the lower edge, above the floating red action.
 *
 * Bulk actions run through `useBulkActionRunner`, the same code as the
 * legacy bulk menu. They act on loaded rows only (the bulk API takes row
 * ids), so after "Select all n" past the loaded page they grey out with that
 * reason; Export, whose API takes the list's query, covers every match.
 */
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import {
  useBulkActionRunner,
  type BulkActionsProps,
} from '@/components/platform/resource-actions/bulk-actions';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import type { FxAnyIconName } from '@/components/fx/icons';
import { fxCount, fxSelectedText } from './fx-words';

export interface FxSelectionBarProps<T> extends BulkActionsProps<T> {
  /** How many are selected (every match after "Select all n"). */
  count: number;
  /** Every match across pages. */
  total: number;
  /** "Select all n" is on: the selection is every match, not ticked rows. */
  allMatching: boolean;
  onSelectAll: () => void;
  onClear: () => void;
  onExport?: () => void;
  iconFor?: Record<string, FxAnyIconName>;
  /** Phones: a floating bar at the lower edge. */
  floating?: boolean;
}

function labelOf<T>(action: ResourceAction<T>, rows: T[]): string {
  return typeof action.label === 'function' ? action.label(rows) : action.label;
}

/** Why a bulk action is greyed for this selection, or undefined (pure). */
export function fxBulkDisabledReason<T>(
  action: ResourceAction<T>,
  rows: T[],
  allMatching: boolean,
  count: number,
): string | undefined {
  if (allMatching && count > rows.length) return `Works on up to ${fxCount(rows.length)} at once`;
  if (action.isDisabled?.(rows)) return action.fxDisabledReason?.(rows) ?? `Not for these ${fxCount(rows.length)}`;
  return undefined;
}

export function FxSelectionBar<T>({
  count,
  total,
  allMatching,
  onSelectAll,
  onClear,
  onExport,
  iconFor,
  floating,
  ...bulk
}: FxSelectionBarProps<T>) {
  const { visible, run, pending, setPending } = useBulkActionRunner(bulk);
  const { rows } = bulk;
  const canSelectAll = !allMatching && total > count;

  return (
    <div
      role="toolbar"
      aria-label="Selection"
      data-fx-selection-bar={floating ? 'floating' : ''}
      className={cn(
        'flex items-center gap-2 animate-in fade-in duration-(--fx-t-hover) ease-(--fx-ease-out)',
        floating
          ? 'fx-see-through fixed inset-x-4 bottom-20 z-(--fx-z-pop) flex-wrap rounded-(--fx-r-l) border border-(--fx-line) px-3 py-2 shadow-[0_8px_24px_var(--fx-shade)] slide-in-from-bottom-2'
          : 'absolute inset-0 z-(--z-sticky-content) flex-wrap rounded-t-(--fx-r-l) bg-(--fx-surface) px-3 slide-in-from-top-1',
      )}
    >
      <span aria-live="polite" className="text-sm font-semibold tabular-nums text-(--fx-ink)">
        {fxSelectedText(count)}
      </span>
      {canSelectAll && (
        <Button
          type="button"
          variant="fx-text"
          className="text-sm text-(--fx-link)"
          onClick={onSelectAll}
        >
          Select all {fxCount(total)}
        </Button>
      )}
      <div className="ms-auto flex flex-wrap items-center justify-end gap-2">
        {visible.map((action) => {
          const Icon = action.icon;
          const reason = fxBulkDisabledReason(action, rows, allMatching, count);
          const label = labelOf(action, rows);
          const named = iconFor?.[action.id];
          return (
            <FxIconAction
              key={action.id}
              label={label}
              icon={named ?? (action.tone === 'destructive' ? 'trash' : 'edit')}
              iconNode={!named && Icon ? <Icon className="size-[1.125rem]" aria-hidden="true" /> : undefined}
              tone={action.tone === 'destructive' ? 'delete' : undefined}
              disabledReason={reason}
              onClick={() => {
                if (action.confirm) setPending(action);
                else void run(action);
              }}
            />
          );
        })}
        {onExport && <FxIconAction label="Export" icon="csv-down" onClick={onExport} />}
        <FxIconAction label="Clear selection" icon="close" onClick={onClear} />
      </div>
      <ConfirmActionDialog
        pending={pending}
        rows={rows}
        onClose={() => setPending(null)}
        onConfirm={(action) => void run(action)}
      />
    </div>
  );
}

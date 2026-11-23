'use client';

/**
 * Next and previous record with the Foundryx UIUX switch on (owner choice
 * from the gap audit, "Coming back to a list; next and previous record"):
 * ‹ and › icon buttons ("Previous record" / "Next record" as tooltips) with
 * "3 of 120" between them in tabular figures. They step through the whole
 * filtered list in its order, across pages, and grey out at the first and
 * last record (owner choice: no wrapping round). The form hides them while
 * the record is being edited, as with the switch off.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useRecordNav } from '@/hooks/use-record-nav';
import type { RecordNavProps } from '@/components/platform/resource-form/record-nav';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { fxCount } from './fx-words';

/** Which arrows are greyed for a 0-based position (pure). */
export function fxRecordNavEnds(index: number, total: number): { atFirst: boolean; atLast: boolean } {
  return { atFirst: index <= 0, atLast: index >= total - 1 };
}

export function FxRecordNav({ guard, ...options }: RecordNavProps) {
  const nav = useRecordNav(options);
  if (!nav.available) return null;

  const attempt = (fn: () => void) => {
    if (guard) guard(fn);
    else fn();
  };
  const { atFirst, atLast } = fxRecordNavEnds(nav.index, nav.total);
  const busy = nav.isNavigating ? 'Opening the record' : undefined;

  return (
    <div data-fx-record-nav="" className="flex items-center gap-1.5">
      <FxIconAction
        mini
        label="Previous record"
        icon="more"
        iconNode={<ChevronLeft aria-hidden="true" className="size-[1.125rem]" />}
        disabledReason={atFirst ? 'This is the first record' : busy}
        onClick={() => attempt(nav.goPrev)}
      />
      <span className="px-1 text-sm font-medium tabular-nums text-(--fx-ink-2)">
        {fxCount(nav.index + 1)} of {fxCount(nav.total)}
      </span>
      <FxIconAction
        mini
        label="Next record"
        icon="more"
        iconNode={<ChevronRight aria-hidden="true" className="size-[1.125rem]" />}
        disabledReason={atLast ? 'This is the last record' : busy}
        onClick={() => attempt(nav.goNext)}
      />
    </div>
  );
}

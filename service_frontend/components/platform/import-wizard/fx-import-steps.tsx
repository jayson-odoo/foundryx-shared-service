'use client';

/**
 * The import wizard's progress (Foundryx UIUX switch only, slice W3-JOBS):
 * numbered dots joined by a line, "Step 2 of 4" over the step's name (playbook
 * "A wizard inside a dialog"). The file step lives in the import dialog; the
 * match, check and import steps on the import page, as today.
 */
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

export const FX_IMPORT_STEPS = ['The file', 'Match the columns', 'Check', 'Import'] as const;

/** `current` is 0-based; `done` marks every step before it as finished. */
export function FxImportSteps({ current, allDone = false }: { current: number; allDone?: boolean }) {
  const total = FX_IMPORT_STEPS.length;
  return (
    <div className="flex flex-col gap-2">
      <ol aria-label="Import steps" className="flex items-center">
        {FX_IMPORT_STEPS.map((name, i) => {
          const done = allDone || i < current;
          const here = !allDone && i === current;
          return (
            <li key={name} className={cn('flex items-center', i > 0 && 'flex-1')}>
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className={cn(
                    'mx-1.5 h-0.5 flex-1 rounded-(--fx-r-pill) transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out)',
                    done || here ? 'bg-(--fx-link)' : 'bg-(--fx-line-2)',
                  )}
                />
              )}
              <span
                aria-current={here ? 'step' : undefined}
                aria-label={`${name}${done ? ', done' : ''}`}
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-(--fx-r-pill) text-xs font-semibold tabular-nums transition-[background-color,color,box-shadow,scale] duration-(--fx-t-hover) ease-(--fx-ease-out)',
                  done && 'bg-(--fx-link) text-(--fx-surface)',
                  here && 'scale-110 bg-(--fx-link-bg) text-(--fx-link) ring-3 ring-(--fx-link)/20',
                  !done && !here && 'border border-(--fx-line-2) text-(--fx-ink-3)',
                )}
              >
                {done ? <Check aria-hidden="true" className="size-3.5" /> : i + 1}
              </span>
            </li>
          );
        })}
      </ol>
      {!allDone && (
        <div>
          <p className="text-xs text-(--fx-ink-3)">
            Step {current + 1} of {total}
          </p>
          <p className="text-sm font-semibold text-(--fx-ink)">{FX_IMPORT_STEPS[current]}</p>
        </div>
      )}
    </div>
  );
}

'use client';

import { Badge } from '@/components/ui/badge';
import { groupSteps, formatVendorDay } from '@/lib/autocount-doc-lookup';
import type { DocLookupStep, DocLookupStepStatus } from '@/types/autocount-doc-lookup';

const STATUS_BADGE: Record<
  DocLookupStepStatus,
  { label: string; variant: 'success' | 'secondary' | 'destructive' | 'warning' | 'info' }
> = {
  hit: { label: 'found', variant: 'success' },
  miss: { label: 'miss', variant: 'secondary' },
  error: { label: 'error', variant: 'destructive' },
  pending: { label: 'waiting', variant: 'info' },
  skipped: { label: 'skipped', variant: 'secondary' },
};

export interface SearchStepsProps {
  steps: DocLookupStep[];
  /** While searching, the first pending step is the one being read. */
  running?: boolean;
}

/** The live search's step chips, grouped by door in plan order. */
export function SearchSteps({ steps, running = false }: SearchStepsProps) {
  const firstPending = running ? steps.findIndex((s) => s.status === 'pending') : -1;
  const groups = groupSteps(steps);
  let index = -1;

  return (
    <div className="flex flex-col gap-3" data-testid="ac-find-steps">
      {groups.map((group) => (
        <div key={`${group.key}-${group.steps[0]?.day}`} className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">{group.label}</span>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
            {group.steps.map((step) => {
              index += 1;
              const reading = index === firstPending;
              const badge = reading ? { label: 'reading', variant: 'warning' as const } : STATUS_BADGE[step.status];
              const tone =
                step.status === 'hit'
                  ? 'border-success bg-success/5'
                  : step.status === 'error'
                    ? 'border-destructive/40 bg-destructive/5'
                    : reading
                      ? 'border-primary bg-primary/5'
                      : 'border-border';
              return (
                <div
                  key={`${step.door}-${step.day}`}
                  title={step.error ?? undefined}
                  data-status={reading ? 'reading' : step.status}
                  className={`flex items-center justify-between gap-1.5 rounded-md border px-2 py-1.5 text-xs ${tone} ${
                    step.status === 'pending' && !reading ? 'text-muted-foreground' : ''
                  }`}
                >
                  <span className="tabular-nums">{formatVendorDay(step.day)}</span>
                  {(step.status !== 'pending' || reading) && (
                    <Badge variant={badge.variant} appearance="light" size="sm">
                      {badge.label}
                    </Badge>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {steps.some((s) => s.status === 'error') && (
        <ul className="flex flex-col gap-0.5 text-xs text-destructive" data-testid="ac-find-step-errors">
          {steps
            .filter((s) => s.status === 'error')
            .map((s) => (
              <li key={`${s.door}-${s.day}`}>
                {formatVendorDay(s.day)}: {s.error ?? 'AutoCount could not be read for this day.'}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

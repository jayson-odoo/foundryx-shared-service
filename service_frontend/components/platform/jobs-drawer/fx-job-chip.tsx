'use client';

/**
 * A job's status chip under the Foundryx UIUX switch (playbook "Status
 * chips"): neutral is a soft blue, done uses the ok set, anything to act on
 * the warn set. Shared by the Jobs sheet, the jobs and imports lists and the
 * job pages of slice W3-JOBS.
 */
import { cn } from '@/lib/utils';
import type { FxJobTone } from './fx-job-items';

const TONE: Record<FxJobTone, string> = {
  ok: 'bg-(--fx-ok-bg) text-(--fx-ok-ink)',
  warn: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
  bad: 'bg-destructive/10 text-destructive',
  run: 'bg-(--fx-link-bg) text-(--fx-link)',
  neutral: 'bg-(--fx-chip) text-(--fx-chip-ink)',
};

export function FxJobChip({
  label,
  tone,
  className,
}: {
  label: string;
  tone: FxJobTone;
  className?: string;
}) {
  return (
    <span
      data-fx-chip={tone}
      className={cn(
        'inline-flex h-6 shrink-0 items-center rounded-(--fx-r-pill) px-2.5 text-xs font-semibold whitespace-nowrap',
        TONE[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}

/** The thin progress bar under a running job, following the real count. */
export function FxJobBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-1.5 w-full overflow-hidden rounded-(--fx-r-pill) bg-(--fx-line)"
    >
      <div
        className="h-full rounded-(--fx-r-pill) bg-(--fx-link) transition-[width] duration-(--fx-t-hover) ease-(--fx-ease-out)"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

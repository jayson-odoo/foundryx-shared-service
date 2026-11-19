'use client';

/**
 * Pieces the omnichannel dashboard and reports share under the Foundryx UIUX
 * switch (playbook 0.71.0 "Charts", "Empty, error and no-access states"):
 * a quiet box, the stat tiles with tabular figures, and the loading and
 * couldn't-load states that sit inside the box and keep its height.
 */
import type { ReactNode } from 'react';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { formatDuration } from '@/lib/duration';
import { cn } from '@/lib/utils';
import type { DurationStats } from '@/types/omnichannel';

export function FxBox({
  title,
  aside,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      data-fx-box=""
      className={cn('flex flex-col gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5', className)}
    >
      {(title || aside) && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {title && <h3 className="text-base font-semibold text-(--fx-ink)">{title}</h3>}
          {aside}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function FxStat({ label, value, big = false }: { label: string; value: ReactNode; big?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-xs text-(--fx-ink-3)">{label}</span>
      <span className={cn('tabular-nums font-semibold text-(--fx-ink)', big ? 'text-2xl' : 'text-lg')}>{value}</span>
    </div>
  );
}

/** A count in the system's format, tabular: 1240 -> "1,240". */
export function fxCount(n: number): string {
  return n.toLocaleString('en-US');
}

/** Loading: the shape of what's coming, inside a box of the same height. */
export function FxLoadingBox({ className, label = 'Loading' }: { className?: string; label?: string }) {
  return (
    <div
      role="status"
      aria-label={label}
      data-fx-chart-state="loading"
      className={cn('flex flex-col justify-end gap-2 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-5', className ?? 'h-56')}
    >
      <div className="flex h-full items-end gap-2" aria-hidden="true">
        {[40, 65, 30, 80, 55, 70, 45].map((h, i) => (
          <span
            key={i}
            className="flex-1 animate-pulse rounded-t-(--fx-r-s) bg-(--fx-surface-2) motion-reduce:animate-none"
            style={{ height: `${h}%` }}
          />
        ))}
      </div>
    </div>
  );
}

/** Couldn't load: what failed in plain words and a "Try again" text button. */
export function FxCouldNotLoad({
  what,
  onRetry,
  className,
}: {
  what: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      data-fx-chart-state="error"
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-5 text-center text-sm',
        className ?? 'h-56',
      )}
    >
      <p className="m-0 font-medium text-(--fx-ink)">Couldn&apos;t load {what}.</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={cn(PRESSED_CLASS, 'font-semibold text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px active:translate-y-0')}
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** A response or resolution time: the median is the answer, the rest beside it. */
export function FxDurationBox({ title, stats, emptyMessage }: { title: string; stats: DurationStats; emptyMessage: string }) {
  if (stats.sampleCount === 0) {
    return (
      <FxBox title={title} bodyClassName="flex h-24 items-center justify-center text-sm text-(--fx-ink-3)">
        {emptyMessage}
      </FxBox>
    );
  }
  return (
    <FxBox title={title} bodyClassName="flex flex-wrap items-end gap-x-6 gap-y-3">
      <FxStat label="Median" value={formatDuration(stats.medianSeconds)} big />
      <FxStat label="P90" value={formatDuration(stats.p90Seconds)} />
      <FxStat label="Average" value={formatDuration(stats.averageSeconds)} />
      <FxStat label="Samples" value={fxCount(stats.sampleCount)} />
    </FxBox>
  );
}

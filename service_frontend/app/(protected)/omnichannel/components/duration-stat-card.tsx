import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDuration } from '@/lib/duration';
import type { DurationStats } from '@/types/omnichannel';
import { useFx } from '@/hooks/use-fx';
import { FxDurationBox } from './fx-report-parts';

/** Foundryx UIUX switch only: what an empty duration card says. */
export function fxDurationEmpty(title: string): string {
  return /resolution/i.test(title) ? 'No conversations closed in this range.' : 'No replies in this range.';
}

/**
 * A response/resolution median + p90 stat card (plan 30, AC-RPT-42/48) -
 * shared by both cards on the dashboard; every duration renders through the
 * ONE `formatDuration` helper. `sampleCount: 0` shows a plain status line,
 * never instructional copy (foolproof-UI empty state, §3.1).
 */
export function DurationStatCard(props: { title: string; stats: DurationStats }) {
  // Foundryx UIUX switch: the median as the answer, in a quiet box; off as today.
  return useFx() ? (
    <FxDurationBox title={props.title} stats={props.stats} emptyMessage={fxDurationEmpty(props.title)} />
  ) : (
    <DurationStatCardLegacy {...props} />
  );
}

function DurationStatCardLegacy({ title, stats }: { title: string; stats: DurationStats }) {
  if (stats.sampleCount === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">
          No data in this range.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-6">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Median</span>
          <span className="text-xl font-heading font-semibold">{formatDuration(stats.medianSeconds)}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">P90</span>
          <span className="text-xl font-heading font-semibold">{formatDuration(stats.p90Seconds)}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Average</span>
          <span className="text-xl font-heading font-semibold">{formatDuration(stats.averageSeconds)}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Samples</span>
          <span className="text-xl font-heading font-semibold">{stats.sampleCount}</span>
        </div>
      </CardContent>
    </Card>
  );
}

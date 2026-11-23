'use client';

/**
 * The dashboard's body under its filter bar. Switch off: today's markup,
 * except that a failed load shows couldn't-load with "Try again" instead of
 * spinning forever. Foundryx UIUX switch on (playbook 0.71.0 "Charts"):
 * quiet boxes, each chart asks one question in its title with the answer
 * above it, numbers in tabular figures, and loading and couldn't-load sit
 * inside the boxes, with "Try again".
 */
import { LoaderCircleIcon } from 'lucide-react';
import { Badge, BadgeDot } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { ReportChart } from '@/components/platform/report-chart';
import { useFx } from '@/hooks/use-fx';
import { formatDuration } from '@/lib/duration';
import type { DashboardResponse } from '@/types/omnichannel';
import { DurationStatCard } from '../../components/duration-stat-card';
import { FxBox, FxCouldNotLoad, FxLoadingBox, FxStat, fxCount } from '../../components/fx-report-parts';
import { LifecycleTiles } from './lifecycle-tiles';
import { OpenedClosedCard } from './opened-closed-card';
import { StateTiles } from './state-tiles';
import { TopAgentsCard } from './top-agents-card';

export interface DashboardContentProps {
  dashboard: DashboardResponse | null;
  loading: boolean;
  error: boolean;
  reload: () => void;
}

export function DashboardContent(props: DashboardContentProps) {
  return useFx() ? <FxDashboardContent {...props} /> : <DashboardContentLegacy {...props} />;
}

function DashboardContentLegacy({ dashboard, loading, error, reload }: DashboardContentProps) {
  // A failed load wins over the spinner, so it never spins forever.
  return error ? (
    <div className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground">
      <span role="alert">Couldn&apos;t load the dashboard.</span>
      <Button mode="link" size="sm" onClick={reload}>
        Try again
      </Button>
    </div>
  ) : loading || !dashboard ? (
    <div className="flex items-center justify-center py-24 text-muted-foreground">
      <LoaderCircleIcon className="size-6 animate-spin" />
    </div>
  ) : (
    <div className="flex flex-col gap-4">
      <StateTiles tiles={dashboard.tiles} />
      <LifecycleTiles stages={dashboard.lifecycle} />
      <OpenedClosedCard buckets={dashboard.buckets} series={dashboard.series} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DurationStatCard title="First response time" stats={dashboard.responseTotals} />
        <DurationStatCard title="Resolution time" stats={dashboard.resolutionTotals} />
      </div>
      <TopAgentsCard agents={dashboard.topAgents} />
    </div>
  );
}

function FxDashboardContent({ dashboard, loading, error, reload }: DashboardContentProps) {
  // A failed load wins over the spinner, so it never spins forever.
  if (error) return <FxCouldNotLoad what="the dashboard" onRetry={reload} className="h-64" />;
  if (loading || !dashboard) {
    return (
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-(--fx-r-l) bg-(--fx-surface-2) motion-reduce:animate-none" />
          ))}
        </div>
        <FxLoadingBox className="h-80" label="Loading the dashboard" />
      </div>
    );
  }

  const tiles: { label: string; value: number }[] = [
    { label: 'Open', value: dashboard.tiles.open },
    { label: 'Assigned', value: dashboard.tiles.assigned },
    { label: 'Unassigned', value: dashboard.tiles.unassigned },
    { label: 'Snoozed', value: dashboard.tiles.snoozed },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) px-4 py-3.5">
            <FxStat label={t.label} value={fxCount(t.value)} big />
          </div>
        ))}
      </div>

      <FxBox title="Contacts by lifecycle stage" bodyClassName="flex flex-wrap gap-3">
        {dashboard.lifecycle.map((stage) => (
          <div key={stage.statusId} className="flex min-w-32 flex-1 flex-col gap-1 rounded-(--fx-r-m) bg-(--fx-surface-2) p-3">
            <Badge variant="secondary" appearance="light" size="sm" className="w-fit">
              <BadgeDot style={stage.color ? { backgroundColor: stage.color } : undefined} />
              {stage.label}
            </Badge>
            <span className="tabular-nums text-lg font-semibold text-(--fx-ink)">{fxCount(stage.count)}</span>
            <span className="tabular-nums text-xs text-(--fx-ink-3)">{stage.percent}%</span>
          </div>
        ))}
      </FxBox>

      <FxBox title="Conversations opened and closed">
        <ReportChart
          buckets={dashboard.buckets}
          series={[
            { key: 'opened', label: 'Opened', points: dashboard.series.opened },
            { key: 'closed', label: 'Closed', points: dashboard.series.closed },
          ]}
          emptyMessage="No conversations opened or closed in this range."
          className="h-64 w-full"
        />
      </FxBox>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DurationStatCard title="First response time" stats={dashboard.responseTotals} />
        <DurationStatCard title="Resolution time" stats={dashboard.resolutionTotals} />
      </div>

      <FxBox title="Agents who closed the most">
        {dashboard.topAgents.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-(--fx-ink-3)">
            No conversations closed in this range.
          </div>
        ) : (
          <ul className="flex flex-col divide-y divide-(--fx-line)">
            {dashboard.topAgents.map((agent) => (
              <li key={agent.userId} className="flex items-center justify-between gap-3 py-2.5">
                <ClampedText text={agent.name} className="text-sm font-medium text-(--fx-ink)" />
                <div className="flex shrink-0 items-center gap-4 text-sm text-(--fx-ink-2)">
                  <span className="tabular-nums">{fxCount(agent.closedCount)} closed</span>
                  <span className="tabular-nums">{formatDuration(agent.medianResponseSeconds)} median reply</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </FxBox>
    </div>
  );
}

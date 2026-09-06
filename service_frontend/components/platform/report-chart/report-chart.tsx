'use client';

/**
 * Report chart adapter (plan 30, D-A9-15) - a thin wrapper over the EXISTING
 * `components/ui/chart.tsx` (shadcn + recharts). Maps `{buckets, series}`
 * onto a `ChartConfig` + recharts data; no `apexcharts`, no new dependency.
 *
 * Data-viz rules (plan §3.1 - the `dataviz` skill isn't installed here):
 * colour ONLY from Foundryx brand CSS variables via `ChartConfig`; a series
 * is identifiable by legend + tooltip, never colour alone; a two-series
 * chart uses one FILLED and one OUTLINED treatment so it still reads in
 * greyscale; bars for counts, zero baseline always, no dual y-axis; the
 * empty state is a short status line, never instructional copy.
 *
 * D-A9-11: a bucket `key` is already LOCAL - `formatBucketLabel` NEVER
 * re-applies a timezone (it formats the calendar digits already in the key,
 * pinned to a `UTC`-labelled `Intl.DateTimeFormat` purely so the formatter
 * doesn't shift them a second time).
 */
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import type { ReportBucket, ReportSeries } from '@/types/omnichannel';

const SERIES_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
];

/** `2026-03-01` -> `1 Mar`; `2026-03-01T09` -> `09:00`; `2026-W10` -> `Wk 10`;
 *  `2026-03` -> `Mar 2026`. Never touches the viewer's timezone - the key's
 *  digits ARE the local calendar value already (D-A9-11). */
export function formatBucketLabel(key: string): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (day) {
    const [, y, m, d] = day;
    const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
    return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(date);
  }
  const hour = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})$/.exec(key);
  if (hour) {
    const [, , , , h] = hour;
    return `${h}:00`;
  }
  const week = /^(\d{4})-W(\d{2})$/.exec(key);
  if (week) return `Wk ${Number(week[2])}`;
  const month = /^(\d{4})-(\d{2})$/.exec(key);
  if (month) {
    const [, y, m] = month;
    const date = new Date(Date.UTC(Number(y), Number(m) - 1, 1));
    return new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
  }
  return key;
}

export interface ReportChartProps {
  buckets: ReportBucket[];
  series: ReportSeries[];
  /** Bars for counts (default); a line reads better for a rate/duration
   *  trend (plan §3.1). */
  variant?: 'bar' | 'line';
  /** Shown instead of the chart when there is nothing to plot. */
  emptyMessage?: string;
  className?: string;
}

export function ReportChart({ buckets, series, variant = 'bar', emptyMessage, className }: ReportChartProps) {
  const hasData = buckets.length > 0 && series.some((s) => s.points.some((p) => p > 0));

  if (!hasData) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        {emptyMessage ?? 'No data in this range.'}
      </div>
    );
  }

  const data = buckets.map((bucket, i) => {
    const row: Record<string, string | number> = { bucket: bucket.key };
    for (const s of series) row[s.key] = s.points[i] ?? 0;
    return row;
  });

  const config: ChartConfig = {};
  series.forEach((s, i) => {
    config[s.key] = { label: s.label, color: SERIES_COLORS[i % SERIES_COLORS.length] };
  });

  const Chart = variant === 'line' ? LineChart : BarChart;

  return (
    <ChartContainer config={config} className={className}>
      <Chart data={data} margin={{ left: 4, right: 4, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="bucket"
          tickFormatter={formatBucketLabel}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          tick={{ fontSize: 11 }}
        />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={32} tick={{ fontSize: 11 }} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(label) => formatBucketLabel(String(label))} />} />
        <ChartLegend content={<ChartLegendContent />} />
        {series.map((s, i) =>
          variant === 'line' ? (
            <Line
              key={s.key}
              dataKey={s.key}
              type="monotone"
              stroke={`var(--color-${s.key})`}
              strokeWidth={2}
              strokeDasharray={i === 1 ? '5 4' : undefined}
              dot={false}
            />
          ) : (
            <Bar
              key={s.key}
              dataKey={s.key}
              fill={`var(--color-${s.key})`}
              // Two-series charts (opened vs closed, incoming vs outgoing) get
              // one filled and one outlined treatment - readable in greyscale
              // without relying on colour alone (plan §3.1).
              fillOpacity={series.length === 2 && i === 1 ? 0.15 : 1}
              stroke={series.length === 2 && i === 1 ? `var(--color-${s.key})` : undefined}
              strokeWidth={series.length === 2 && i === 1 ? 2 : 0}
              radius={[3, 3, 0, 0]}
            />
          ),
        )}
      </Chart>
    </ChartContainer>
  );
}

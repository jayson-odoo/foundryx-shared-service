'use client';

/**
 * The report chart under the Foundryx UIUX switch (playbook 0.71.0 "Charts").
 * `ReportChart` renders it while the switch is on, with the same props.
 *
 * - Quiet: light gridlines in `--fx-line`, a few axis ticks, no borders, no
 *   legend box. The series' names sit in one key line above the chart with
 *   each series' total, so nothing has to be looked up.
 * - Colour: the first series (the thing the chart is about) is `--fx-link`;
 *   the rest are muted. Red is never used to tell series apart.
 * - Pointing shows the values in a tooltip styled like every other tooltip,
 *   with a soft guide (a band on bars, a vertical line on lines).
 * - States sit inside the chart's own box, which keeps its height.
 * - Motion: bars grow and lines draw once (0.6 s); reduced motion shows them
 *   at once. Times on an hourly axis read on the 12-hour clock.
 */
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { ChartContainer, ChartTooltip, type ChartConfig } from '@/components/ui/chart';
import { cn } from '@/lib/utils';
import type { ReportBucket, ReportSeries } from '@/types/omnichannel';
import { formatBucketLabel } from './report-chart';

/** Series colours: the first in `--fx-link`, the rest muted. */
const FX_SERIES = ['var(--fx-link)', 'var(--fx-ink-3)', 'var(--fx-line-2)'];

export function fxSeriesColor(index: number): string {
  return FX_SERIES[Math.min(index, FX_SERIES.length - 1)];
}

/** Like `formatBucketLabel`, with hours on the 12-hour clock ("9 am"). */
export function fxBucketLabel(key: string): string {
  const hour = /^\d{4}-\d{2}-\d{2}T(\d{2})$/.exec(key);
  if (hour) {
    const h = Number(hour[1]);
    return `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'am' : 'pm'}`;
  }
  return formatBucketLabel(key);
}

/** 412800 -> "412.8k" on an axis only; values elsewhere stay whole. */
export function fxAxisNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${+(value / 1_000_000).toFixed(1)}m`;
  if (Math.abs(value) >= 1_000) return `${+(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function reducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

interface TipEntry {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string;
}

function FxChartTip({
  active,
  payload,
  label,
  series,
}: {
  active?: boolean;
  payload?: TipEntry[];
  label?: string | number;
  series: ReportSeries[];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div
      role="tooltip"
      data-fx-tip=""
      className="w-max max-w-[300px] rounded-(--fx-r-m) border border-(--fx-line) bg-[color-mix(in_srgb,var(--fx-surface)_var(--fx-tip-bg,92%),transparent)] px-2.5 py-1.5 text-sm text-(--fx-ink) shadow-[0_8px_24px_var(--fx-shade)] backdrop-blur-[6px]"
    >
      <div className="mb-1 font-semibold">{fxBucketLabel(String(label ?? ''))}</div>
      {payload.map((entry) => {
        const index = series.findIndex((s) => s.key === entry.dataKey);
        const name = index >= 0 ? series[index].label : String(entry.name ?? '');
        return (
          <div key={String(entry.dataKey)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-(--fx-ink-2)">
              <span aria-hidden="true" className="size-2 rounded-full" style={{ background: fxSeriesColor(index) }} />
              {name}
            </span>
            <span className="tabular-nums font-semibold">{Number(entry.value ?? 0).toLocaleString('en-US')}</span>
          </div>
        );
      })}
    </div>
  );
}

export interface FxReportChartProps {
  buckets: ReportBucket[];
  series: ReportSeries[];
  variant?: 'bar' | 'line';
  emptyMessage?: string;
  className?: string;
  fxTotals?: Record<string, number>;
}

export function FxReportChart({ buckets, series, variant = 'bar', emptyMessage, className, fxTotals }: FxReportChartProps) {
  const hasData = buckets.length > 0 && series.some((s) => s.points.some((p) => p > 0));

  if (!hasData) {
    return (
      <div
        data-fx-chart-state="empty"
        className={cn('flex items-center justify-center text-center text-sm text-(--fx-ink-3)', className ?? 'h-56')}
      >
        {emptyMessage ?? 'Nothing happened in this range.'}
      </div>
    );
  }

  const data = buckets.map((bucket, i) => {
    const row: Record<string, string | number> = { bucket: bucket.key };
    for (const s of series) row[s.key] = s.points[i] ?? 0;
    return row;
  });
  const config: ChartConfig = Object.fromEntries(series.map((s) => [s.key, { label: s.label }]));
  const animate = !reducedMotion();
  const Chart = variant === 'line' ? LineChart : BarChart;

  return (
    <div className="flex flex-col gap-3" data-fx-chart="">
      {variant === 'bar' && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Totals">
          {series.map((s, i) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: fxSeriesColor(i) }} />
              <span className="tabular-nums font-semibold text-(--fx-ink)">
                {(fxTotals?.[s.key] ?? s.points.reduce((a, b) => a + b, 0)).toLocaleString('en-US')}
              </span>
              <span className="text-(--fx-ink-3)">{s.label}</span>
            </li>
          ))}
        </ul>
      )}
      <ChartContainer config={config} className={cn('tabular-nums', className)}>
        <Chart data={data} margin={{ left: 4, right: 4, top: 8, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--fx-line)" />
          <XAxis
            dataKey="bucket"
            tickFormatter={fxBucketLabel}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
            tick={{ fontSize: 11, fill: 'var(--fx-ink-3)' }}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            width={36}
            tickCount={4}
            tickFormatter={fxAxisNumber}
            tick={{ fontSize: 11, fill: 'var(--fx-ink-3)' }}
          />
          <ChartTooltip
            cursor={variant === 'line' ? { stroke: 'var(--fx-line-2)' } : { fill: 'var(--fx-link-bg)' }}
            content={<FxChartTip series={series} />}
          />
          {series.map((s, i) =>
            variant === 'line' ? (
              <Line
                key={s.key}
                dataKey={s.key}
                type="monotone"
                stroke={fxSeriesColor(i)}
                strokeWidth={2}
                strokeDasharray={i === 1 ? '5 4' : undefined}
                dot={false}
                isAnimationActive={animate}
                animationDuration={600}
                animationEasing="ease-out"
              />
            ) : (
              <Bar
                key={s.key}
                dataKey={s.key}
                fill={fxSeriesColor(i)}
                radius={[3, 3, 0, 0]}
                isAnimationActive={animate}
                animationDuration={600}
                animationEasing="ease-out"
              />
            ),
          )}
        </Chart>
      </ChartContainer>
    </div>
  );
}

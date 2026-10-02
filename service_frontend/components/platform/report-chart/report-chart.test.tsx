import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';
import { ReportChart, formatBucketLabel } from './report-chart';
import type { ReportBucket, ReportSeries } from '@/types/omnichannel';

// recharts' <ResponsiveContainer> measures its host element via
// getBoundingClientRect and refuses to render children at 0x0 - jsdom never
// lays anything out, so every chart test needs a non-zero stub (scoped to
// this file, not the global setup, since most components don't need it).
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ width: 600, height: 300, top: 0, left: 0, right: 600, bottom: 300, x: 0, y: 0, toJSON() {} }),
  });
});

describe('formatBucketLabel', () => {
  it('formats a day key without touching the viewer timezone (D-A9-11)', () => {
    // Asserted regardless of the runtime's own timezone - the key's digits
    // ARE the local calendar value already, so a UTC-pinned formatter must
    // never shift them (the classic double-timezone-conversion bug).
    expect(formatBucketLabel('2026-03-01')).toBe('1 Mar');
  });

  it('formats an hour key', () => {
    expect(formatBucketLabel('2026-03-01T09')).toBe('09:00');
  });

  it('formats a week key', () => {
    expect(formatBucketLabel('2026-W10')).toBe('Wk 10');
  });

  it('formats a month key', () => {
    expect(formatBucketLabel('2026-03')).toBe('Mar 2026');
  });

  it('falls back to the raw key for anything unrecognized', () => {
    expect(formatBucketLabel('not-a-key')).toBe('not-a-key');
  });
});

const BUCKETS: ReportBucket[] = [
  { key: '2026-03-01', startsAt: '2026-02-28T16:00:00Z', endsAt: '2026-03-01T16:00:00Z' },
  { key: '2026-03-02', startsAt: '2026-03-01T16:00:00Z', endsAt: '2026-03-02T16:00:00Z' },
];

describe('ReportChart', () => {
  it('renders the empty state when every series is all-zero', () => {
    const series: ReportSeries[] = [{ key: 'opened', label: 'Opened', points: [0, 0] }];
    render(<ReportChart buckets={BUCKETS} series={series} />);
    expect(screen.getByText('No data in this range.')).toBeInTheDocument();
  });

  it('renders a custom empty message', () => {
    render(<ReportChart buckets={[]} series={[]} emptyMessage="Nothing yet." />);
    expect(screen.getByText('Nothing yet.')).toBeInTheDocument();
  });

  it('renders the legend for each series when there is data', () => {
    const series: ReportSeries[] = [
      { key: 'opened', label: 'Opened', points: [2, 1] },
      { key: 'closed', label: 'Closed', points: [1, 1] },
    ];
    render(<ReportChart buckets={BUCKETS} series={series} />);
    expect(screen.getByText('Opened')).toBeInTheDocument();
    expect(screen.getByText('Closed')).toBeInTheDocument();
  });
});

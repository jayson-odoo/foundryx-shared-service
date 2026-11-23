/**
 * The omnichannel dashboard and reports under the Foundryx UIUX switch (slice
 * W2-BCAST): the chart rules (one question per chart with its answer above,
 * quiet, series colours, the 12-hour axis), states inside the box with "Try
 * again", the zone line, and that Export sends the same request in both looks.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { ReportChart, fxAxisNumber, fxBucketLabel, fxSeriesColor } from '@/components/platform/report-chart';
import type { DashboardResponse, ReportResponse } from '@/types/omnichannel';

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
  permissions: new Set<string>(['reports.read', 'reports.export']),
  dashboard: { dashboard: null as unknown, loading: false, error: false },
  report: { loading: false, error: false },
}));

vi.mock('@/lib/toast', () => {
  const t = (kind: string) => (...args: unknown[]) => {
    h.calls.push([`toast.${kind}`, ...args]);
    return 'toast-id';
  };
  return {
    toast: {
      success: t('success'),
      error: t('error'),
      info: t('info'),
      warning: t('warning'),
      message: t('message'),
      custom: t('custom'),
      dismiss: t('dismiss'),
      fxDone: t('fxDone'),
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/omnichannel/reports',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => h.permissions.has(key), ready: true, permissions: h.permissions }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({
    workspaceId: 'ws-1',
    workspaces: [
      { id: 'ws-1', name: 'Sales' },
      { id: 'ws-2', name: 'Support' },
    ],
    ready: true,
    setWorkspaceId: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({
  useWorkspaceMembers: () => ({ members: [{ userId: 'u-1', name: 'Kay Tan', email: 'kay@example.com' }] }),
}));
vi.mock('@/hooks/use-workspace-channels', () => ({
  useWorkspaceChannels: () => ({ options: [{ id: 'chn-1', name: 'Maju Sales WhatsApp' }] }),
}));
vi.mock('@/hooks/use-report-meta', () => ({
  useReportMeta: () => ({
    meta: {
      reports: [
        { key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true },
        { key: 'responses', label: 'Responses', supportsGroupBy: ['user'], paginated: false, exportable: true },
        { key: 'messages', label: 'Messages', supportsGroupBy: ['channel'], paginated: false, exportable: true },
      ],
      granularities: ['day', 'week'],
      dimensions: { team: { available: false } },
    },
    loading: false,
    error: false,
  }),
}));
vi.mock('@/services/omnichannel-report-service', () => ({
  omnichannelReportService: {
    exportReport: (...args: unknown[]) => {
      h.calls.push(['report.export', ...args]);
      return Promise.resolve('a,b\n1,2\n');
    },
    meta: vi.fn(),
    report: vi.fn(),
    dashboard: vi.fn(),
  },
}));
vi.mock('@/hooks/use-omnichannel-dashboard', () => ({
  useOmnichannelDashboard: (...args: unknown[]) => {
    h.calls.push(['dashboard', ...args]);
    return { ...h.dashboard, reload: () => h.calls.push(['dashboard.reload']) };
  },
}));

const BUCKETS = ['2026-11-12', '2026-11-13', '2026-11-14'].map((key) => ({
  key,
  startsAt: `${key}T00:00:00Z`,
  endsAt: `${key}T23:59:59Z`,
}));

const STATS = { medianSeconds: 95, p90Seconds: 1800, averageSeconds: 400, sampleCount: 42 };

function reportFor(key: string): ReportResponse {
  const base = {
    reportKey: key,
    timezone: 'Asia/Kuala_Lumpur',
    range: { from: '2026-11-12', to: '2026-11-18' },
    granularity: 'day',
    buckets: BUCKETS,
  } as const;
  if (key === 'conversations') {
    return {
      ...base,
      series: [
        { key: 'opened', label: 'Opened', points: [4, 9, 2] },
        { key: 'closed', label: 'Closed', points: [3, 6, 5] },
        { key: 'reopened', label: 'Reopened', points: [0, 1, 0] },
      ],
      rows: [],
      totals: { opened: 15, closed: 14, reopened: 1 },
    } as ReportResponse;
  }
  if (key === 'messages') {
    return {
      ...base,
      series: [
        { key: 'incoming', label: 'Incoming', points: [40, 90, 22] },
        { key: 'outgoing', label: 'Outgoing', points: [31, 60, 25] },
      ],
      rows: [{ channelId: 'chn-1', name: 'Maju Sales WhatsApp', incoming: 152, outgoing: 116 }],
      totals: { incoming: 152, outgoing: 116 },
    } as ReportResponse;
  }
  return {
    ...base,
    series: [],
    rows: [
      { bucket: 'lt1m', label: 'Under 1 min', count: 20, percent: 48 },
      { bucket: 'lt5m', label: '1 to 5 min', count: 22, percent: 52 },
    ],
    totals: STATS,
  } as ReportResponse;
}

vi.mock('@/hooks/use-omnichannel-report', () => ({
  useOmnichannelReport: (ws: string, key: string, filters: unknown) => {
    h.calls.push(['report', ws, key, filters]);
    return { report: reportFor(key), ...h.report, reload: () => h.calls.push(['report.reload']) };
  },
}));

function dashboard(): DashboardResponse {
  return {
    timezone: 'Asia/Kuala_Lumpur',
    range: { from: '2026-11-12', to: '2026-11-18' },
    granularity: 'day',
    buckets: BUCKETS,
    tiles: { open: 128, assigned: 97, unassigned: 31, snoozed: 4 },
    lifecycle: [
      { statusId: 's1', key: 'new', label: 'New lead', color: '#3b82f6', sortOrder: 1, count: 1240, percent: 62 },
      { statusId: 's2', key: 'won', label: 'Customer', color: null, sortOrder: 2, count: 760, percent: 38 },
    ],
    series: { opened: [4, 9, 2], closed: [3, 6, 5] },
    responseTotals: STATS,
    resolutionTotals: { medianSeconds: null, p90Seconds: null, averageSeconds: null, sampleCount: 0 },
    topAgents: [{ userId: 'u-1', name: 'Kay Tan', closedCount: 12, medianResponseSeconds: 80 }],
  };
}

// Imported after the mocks.
import DashboardPage from '../dashboard/page';
import ReportsPage from '../reports/page';
import { fxDurationEmpty } from './duration-stat-card';

function render(ui: ReactElement, fx: boolean) {
  return rtlRender(
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{ui}</SettingsProvider>
    </FxProvider>,
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

beforeAll(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-18T04:00:00Z') });
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
});
afterAll(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  h.calls.length = 0;
  h.dashboard = { dashboard: dashboard(), loading: false, error: false };
  h.report = { loading: false, error: false };
  resetPageActionsForTests();
  window.history.replaceState(null, '', '/omnichannel/reports');
});

describe('chart words (pure)', () => {
  it('hourly axes read on the 12-hour clock, the rest as before', () => {
    expect(fxBucketLabel('2026-11-18T00')).toBe('12 am');
    expect(fxBucketLabel('2026-11-18T09')).toBe('9 am');
    expect(fxBucketLabel('2026-11-18T13')).toBe('1 pm');
    expect(fxBucketLabel('2026-11-18')).toBe('18 Nov');
    expect(fxBucketLabel('2026-W10')).toBe('Wk 10');
  });

  it('numbers shorten only on axes', () => {
    expect(fxAxisNumber(950)).toBe('950');
    expect(fxAxisNumber(412800)).toBe('412.8k');
    expect(fxAxisNumber(2_000_000)).toBe('2m');
  });

  it('the first series is the link colour, the rest muted, never red', () => {
    expect(fxSeriesColor(0)).toBe('var(--fx-link)');
    expect([fxSeriesColor(1), fxSeriesColor(2), fxSeriesColor(5)]).not.toContain('var(--fx-act)');
  });

  it('empty duration boxes say what is missing', () => {
    expect(fxDurationEmpty('Resolution time')).toBe('No conversations closed in this range.');
    expect(fxDurationEmpty('First response time')).toBe('No replies in this range.');
  });
});

describe('the chart', () => {
  it('shows the answer above it and keeps its box when empty', () => {
    render(
      <ReportChart
        buckets={BUCKETS}
        series={[
          { key: 'opened', label: 'Opened', points: [4, 9, 2] },
          { key: 'closed', label: 'Closed', points: [3, 6, 5] },
        ]}
        fxTotals={{ opened: 15 }}
        className="h-64 w-full"
      />,
      true,
    );
    const totals = screen.getByRole('list', { name: 'Totals' });
    expect(totals.textContent).toBe('15Opened14Closed');
    const { container } = render(<ReportChart buckets={[]} series={[]} className="h-64 w-full" />, true);
    const empty = container.querySelector('[data-fx-chart-state="empty"]') as HTMLElement;
    expect(empty.className).toContain('h-64');
    expect(empty.textContent).toBe('Nothing happened in this range.');
  });
});

describe('the dashboard', () => {
  it('names the zone the days count in and asks one question per chart', async () => {
    window.history.replaceState(null, '', '/omnichannel/dashboard');
    render(<DashboardPage />, true);
    await settle();
    expect(screen.getByText('Kuala Lumpur time (GMT+8)')).toBeInTheDocument();
    expect(screen.queryByText(/^Timezone:/)).toBeNull();
    expect(screen.getByRole('heading', { name: 'Conversations opened and closed' })).toBeInTheDocument();
    expect(screen.getByText('1,240')).toBeInTheDocument();
  });

  it("couldn't load: says so in the box and Try again reloads", async () => {
    h.dashboard = { dashboard: null, loading: false, error: true };
    window.history.replaceState(null, '', '/omnichannel/dashboard');
    render(<DashboardPage />, true);
    await settle();
    expect(screen.getByRole('alert').textContent).toContain("Couldn't load the dashboard.");
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(h.calls).toContainEqual(['dashboard.reload']);
  });
});

describe('the reports page', () => {
  it('Export is an icon action and sends the same request as the switch-off button', async () => {
    window.history.replaceState(null, '', '/omnichannel/reports?report=messages');
    const off = render(<ReportsPage />, false);
    await settle();
    h.calls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await settle();
    const offCalls = JSON.parse(JSON.stringify(h.calls.filter((c) => (c as string[])[0] === 'report.export')));
    off.unmount();

    window.history.replaceState(null, '', '/omnichannel/reports?report=messages');
    render(<ReportsPage />, true);
    await settle();
    expect(screen.queryByRole('button', { name: 'Export' })).toBeNull();
    h.calls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Export Messages CSV' }));
    await settle();
    const onCalls = JSON.parse(JSON.stringify(h.calls.filter((c) => (c as string[])[0] === 'report.export')));
    expect(offCalls).toHaveLength(1);
    expect(onCalls).toEqual(offCalls);
  });

  it("a report that couldn't load offers Try again", async () => {
    h.report = { loading: false, error: true };
    render(<ReportsPage />, true);
    await settle();
    expect(screen.getByRole('alert').textContent).toContain("Couldn't load this report.");
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(h.calls).toContainEqual(['report.reload']);
  });

  it('the conversations report puts its totals above the chart', async () => {
    render(<ReportsPage />, true);
    await settle();
    expect(screen.getByRole('heading', { name: 'Conversations opened, closed and reopened' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Totals' }).textContent).toBe('15Opened14Closed1Reopened');
  });
});

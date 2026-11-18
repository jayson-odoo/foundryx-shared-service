/**
 * Switch-off parity for the omnichannel dashboard and reports pages and the
 * shared report chart (Foundryx UIUX, slice W2-BCAST). Recorded on the code
 * BEFORE the slice changed anything, so a later change that alters what a
 * user sees or what reaches the backend with the switch off fails here. A
 * change that needs one of these snapshots updated is wrong by definition:
 * fix the code, never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { ReportChart } from '@/components/platform/report-chart';
import type { DashboardResponse, ReportResponse } from '@/types/omnichannel';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';

/** React 19's `_r_N_` ids and recharts' generated ids renamed in order. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/recharts\d+-clip/g, 'recharts-clip')
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>');
}

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
    return { ...h.dashboard, reload: vi.fn() };
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
    return { report: reportFor(key), ...h.report };
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

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

function calls(): unknown[] {
  return JSON.parse(JSON.stringify(h.calls));
}

beforeAll(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-18T04:00:00Z') });
});
afterAll(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  h.calls.length = 0;
  h.dashboard = { dashboard: dashboard(), loading: false, error: false };
  h.report = { loading: false, error: false };
  window.history.replaceState(null, '', '/omnichannel/reports');
});

describe('switch-off parity: dashboard', () => {
  it('renders the dashboard as today', async () => {
    window.history.replaceState(null, '', '/omnichannel/dashboard');
    const { container } = render(<DashboardPage />);
    await screen.findByText('Top agents');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(calls()).toMatchSnapshot();
  });

  it('renders the dashboard while loading as today', async () => {
    h.dashboard = { dashboard: null, loading: true, error: false };
    window.history.replaceState(null, '', '/omnichannel/dashboard');
    const { container } = render(<DashboardPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('switch-off parity: reports', () => {
  it('renders the conversations report as today', async () => {
    const { container } = render(<ReportsPage />);
    await screen.findByText('Conversations over time');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders the messages report as today', async () => {
    window.history.replaceState(null, '', '/omnichannel/reports?report=messages');
    const { container } = render(<ReportsPage />);
    await screen.findByText('Messages over time');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders the responses report as today', async () => {
    window.history.replaceState(null, '', '/omnichannel/reports?report=responses');
    const { container } = render(<ReportsPage />);
    await screen.findByText('Response time breakdown');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a report that could not load as today', async () => {
    h.report = { loading: false, error: true };
    const { container } = render(<ReportsPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('exports with the same request as today', async () => {
    window.history.replaceState(null, '', '/omnichannel/reports?report=messages');
    render(<ReportsPage />);
    await screen.findByText('Messages over time');
    await settle();
    h.calls.length = 0;
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await settle();
    expect(calls().filter((c) => (c as string[])[0] !== 'report')).toMatchSnapshot();
  });
});

describe('switch-off parity: report chart', () => {
  it('renders an empty chart as today', () => {
    const { container } = render(<ReportChart buckets={[]} series={[]} className="h-64 w-full" />);
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a chart with data as today', () => {
    const { container } = render(
      <ReportChart
        buckets={BUCKETS}
        series={[
          { key: 'opened', label: 'Opened', points: [4, 9, 2] },
          { key: 'closed', label: 'Closed', points: [3, 6, 5] },
        ]}
        className="h-64 w-full"
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

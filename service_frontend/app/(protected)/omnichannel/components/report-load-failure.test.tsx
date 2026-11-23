/**
 * A dashboard or report whose load fails, in the look with the Foundryx UIUX
 * switch off (and on, for the same path): the spinner stops, the couldn't-load
 * words show, and "Try again" reads it again. The real hooks run here; only
 * the service is mocked, so the first load rejects before any data arrived.
 */
import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { useOmnichannelDashboard } from '@/hooks/use-omnichannel-dashboard';
import type { DashboardResponse, ReportFilters, ReportResponse } from '@/types/omnichannel';
import { DashboardContent } from '../dashboard/components/dashboard-content';
import { ConversationsReport } from '../reports/components/conversations-report';
import { MessagesReport } from '../reports/components/messages-report';

const h = vi.hoisted(() => ({
  dashboard: vi.fn(),
  report: vi.fn(),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'Asia/Kuala_Lumpur', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/services/omnichannel-report-service', () => ({
  omnichannelReportService: {
    dashboard: (...args: unknown[]) => h.dashboard(...args),
    report: (...args: unknown[]) => h.report(...args),
  },
}));

const FILTERS = { from: '2026-11-12', to: '2026-11-18', tz: 'Asia/Kuala_Lumpur', granularity: 'day' } as ReportFilters;

const BUCKETS = ['2026-11-12', '2026-11-13'].map((key) => ({
  key,
  startsAt: `${key}T00:00:00Z`,
  endsAt: `${key}T23:59:59Z`,
}));
const STATS = { medianSeconds: 95, p90Seconds: 1800, averageSeconds: 400, sampleCount: 42 };

const DASHBOARD: DashboardResponse = {
  timezone: 'Asia/Kuala_Lumpur',
  range: { from: '2026-11-12', to: '2026-11-18' },
  granularity: 'day',
  buckets: BUCKETS,
  tiles: { open: 128, assigned: 97, unassigned: 31, snoozed: 4 },
  lifecycle: [],
  series: { opened: [4, 9], closed: [3, 6] },
  responseTotals: STATS,
  resolutionTotals: STATS,
  topAgents: [{ userId: 'u-1', name: 'Kay Tan', closedCount: 12, medianResponseSeconds: 80 }],
};

const CONVERSATIONS = {
  reportKey: 'conversations',
  timezone: 'Asia/Kuala_Lumpur',
  range: { from: '2026-11-12', to: '2026-11-18' },
  granularity: 'day',
  buckets: BUCKETS,
  series: [{ key: 'opened', label: 'Opened', points: [4, 9] }],
  rows: [],
  totals: { opened: 13, closed: 9, reopened: 1 },
} as unknown as ReportResponse;

function Dashboard() {
  const state = useOmnichannelDashboard('ws-1', FILTERS);
  return <DashboardContent {...state} />;
}

function render(ui: ReactElement, fx: boolean) {
  return rtlRender(fx ? <FxProvider initial initialTheme={FX_DEFAULT_THEME}>{ui}</FxProvider> : ui);
}

beforeEach(() => {
  h.dashboard.mockReset();
  h.report.mockReset();
});

describe.each([
  ['switch off', false],
  ['switch on', true],
])('a failed load, %s', (_name, fx) => {
  it('the dashboard stops loading, says it could not load, and Try again reads it again', async () => {
    h.dashboard.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(DASHBOARD);
    const { container } = render(<Dashboard />, fx);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the dashboard.");
    expect(container.querySelector('.animate-spin')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(h.dashboard).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(h.dashboard).toHaveBeenCalledTimes(2));
    expect(h.dashboard).toHaveBeenLastCalledWith('ws-1', FILTERS);
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(await screen.findByText('Kay Tan')).toBeInTheDocument();
  });

  it('a report stops loading, says it could not load, and Try again reads it again', async () => {
    h.report.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(CONVERSATIONS);
    const { container } = render(<ConversationsReport workspaceId="ws-1" filters={FILTERS} />, fx);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load this report.");
    expect(container.querySelector('.animate-spin')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(h.report).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(h.report).toHaveBeenCalledTimes(2));
    expect(h.report).toHaveBeenLastCalledWith('ws-1', 'conversations', FILTERS);
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('a report that keeps failing never goes back to the spinner for good', async () => {
    h.report.mockRejectedValue(new Error('boom'));
    const { container } = render(<MessagesReport workspaceId="ws-1" filters={FILTERS} />, fx);

    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(h.report).toHaveBeenCalledTimes(2));
    expect((await screen.findByRole('alert')).textContent).toContain("Couldn't load this report.");
    expect(container.querySelector('.animate-spin')).toBeNull();
  });
});

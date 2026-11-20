/**
 * N-1 (plan 30, review round 2): the reports page must not flash - or
 * dead-end on - "Couldn't load the reports." while the catalog is simply
 * still on its way.
 *
 * `page.test.tsx` mocks `useReportMeta` synchronously, which is exactly why
 * it could not see this: the bug lives in the REAL hook's state sequence.
 * `useReportMeta(null)` (pre-`ready`) settles at loading=false / meta=null /
 * error=false, and the commit right after the workspace id lands - before
 * the fetch effect re-runs - still carries that state. The page used to read
 * `!meta` there as an error. So this suite keeps the real hook and drives
 * the service with a deferred promise instead.
 */
import { act, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { ReportMeta } from '@/types/omnichannel';
import ReportsPage from './page';

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

const META: ReportMeta = {
  reports: [
    { key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true },
  ],
  granularities: ['day'],
  dimensions: { team: { available: false } },
};

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set(['reports.read', 'reports.export']) }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'Asia/Kuala_Lumpur',
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ ready: true, label: (k: string) => k, labelPlural: (k: string) => k, t: (k: string) => k, refetch: vi.fn() }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: [] }) }));
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/hooks/use-omnichannel-report', () => ({
  useOmnichannelReport: (_ws: string, key: string) => ({
    report: {
      reportKey: key,
      timezone: 'Asia/Kuala_Lumpur',
      range: { from: '2026-03-01', to: '2026-03-07' },
      granularity: 'day',
      buckets: [],
      series: [],
      rows: [],
      totals: { opened: 0, closed: 0, reopened: 0 },
    },
    loading: false,
    error: false,
  }),
}));

// The workspace resolution is the thing that flips mid-mount in production
// (`useActiveWorkspace` resolves asynchronously), so it is a mutable stub.
const workspaceState = { workspaceId: null as string | null, ready: false };
vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({
    workspaceId: workspaceState.workspaceId,
    workspaces: [],
    ready: workspaceState.ready,
    setWorkspaceId: vi.fn(),
  }),
}));

vi.mock('@/services/omnichannel-report-service', () => ({
  omnichannelReportService: {
    exportReport: vi.fn(),
    meta: vi.fn(),
    report: vi.fn(),
    dashboard: vi.fn(),
  },
}));

const ERROR_COPY = /Couldn't load the reports\./;

/** Records EVERY committed DOM state (not just the settled one), so a
 *  transient error paint between two commits inside one `act` is caught. */
function watchForErrorPaint(): { sawError: () => boolean; stop: () => void } {
  let seen = false;
  const inspect = (records: MutationRecord[]) => {
    // Read the RECORDS, not the live body: the observer callback is a
    // microtask, by which time a later commit may already have replaced the
    // transient paint. The added nodes carry the text that was painted.
    for (const record of records) {
      record.addedNodes.forEach((node) => {
        if (ERROR_COPY.test(node.textContent ?? '')) seen = true;
      });
      if (record.type === 'characterData' && ERROR_COPY.test(record.target.textContent ?? '')) seen = true;
    }
  };
  const observer = new MutationObserver(inspect);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  return {
    sawError: () => {
      inspect(observer.takeRecords());
      if (ERROR_COPY.test(document.body.textContent ?? '')) seen = true;
      return seen;
    },
    stop: () => observer.disconnect(),
  };
}

beforeEach(() => {
  workspaceState.workspaceId = null;
  workspaceState.ready = false;
  vi.mocked(omnichannelReportService.meta).mockReset();
  window.history.replaceState(null, '', '/omnichannel/reports');
});

describe('Reports page - catalog loading state (N-1)', () => {
  it('spins (never errors) between the workspace id landing and the catalog arriving', async () => {
    let resolveMeta: (m: ReportMeta) => void = () => {};
    vi.mocked(omnichannelReportService.meta).mockImplementation(
      () => new Promise<ReportMeta>((resolve) => { resolveMeta = resolve; }),
    );
    const watch = watchForErrorPaint();

    const { rerender } = render(<ReportsPage />);
    expect(watch.sawError()).toBe(false);

    // The workspace resolves. The very next commit carries the real hook's
    // post-null state (loading=false, meta=null, error=false) - the paint
    // the old code turned into a dead-end error.
    workspaceState.workspaceId = 'ws-1';
    workspaceState.ready = true;
    await act(async () => {
      rerender(<SettingsProvider><ReportsPage /></SettingsProvider>);
    });
    expect(watch.sawError()).toBe(false);
    await waitFor(() => expect(omnichannelReportService.meta).toHaveBeenCalledWith('ws-1'));
    expect(watch.sawError()).toBe(false);

    await act(async () => {
      resolveMeta(META);
    });
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Report' })).toBeInTheDocument());
    expect(watch.sawError()).toBe(false);
    watch.stop();
  });

  it('renders the page with an empty body - not the error - when there is no workspace at all (BL-SS-081)', async () => {
    workspaceState.workspaceId = null;
    workspaceState.ready = true;
    render(<ReportsPage />);
    await waitFor(() => expect(screen.queryByText(ERROR_COPY)).not.toBeInTheDocument());
    // The header + report chooser still render; the catalog fetch was never
    // attempted (there is no workspace to fetch it for).
    expect(screen.getByRole('combobox', { name: 'Report' })).toBeInTheDocument();
    expect(omnichannelReportService.meta).not.toHaveBeenCalled();
  });

  it('shows the error state only on an actual catalog fetch failure', async () => {
    vi.mocked(omnichannelReportService.meta).mockRejectedValue(new Error('boom'));
    workspaceState.workspaceId = 'ws-1';
    workspaceState.ready = true;
    render(<ReportsPage />);
    await waitFor(() => expect(screen.getByText(ERROR_COPY)).toBeInTheDocument());
  });
});

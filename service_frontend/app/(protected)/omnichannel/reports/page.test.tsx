/**
 * Reports page (plan 30, AC-RPT-47/52) - the Export control is gated
 * `reports.export` (UX only, `useCan` - the API is the real boundary); a
 * user holding `reports.read` but not `.export` must still see every report,
 * just no Export button.
 *
 * Review round 1 adds: S-5 (the export request must carry the group-by the
 * user is actually looking at - it lived in renderer-local `useState`, so
 * Export always sent the ungrouped shape) and the report-switch nit (the
 * shared filters must survive changing report).
 */
import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import ReportsPage from './page';

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

let permissions = new Set<string>();
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => permissions.has(key), ready: true, permissions }),
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
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({ workspaceId: 'ws-1', workspaces: [], ready: true, setWorkspaceId: vi.fn() }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: [] }) }));
vi.mock('@/hooks/use-report-meta', () => ({
  useReportMeta: () => ({
    meta: {
      reports: [
        { key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true },
        { key: 'responses', label: 'Responses', supportsGroupBy: ['user'], paginated: false, exportable: true },
      ],
      granularities: ['day'],
      dimensions: { team: { available: false } },
    },
    loading: false,
    error: false,
  }),
}));
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/services/omnichannel-report-service', () => ({
  omnichannelReportService: {
    exportReport: vi.fn().mockResolvedValue('a,b\n1,2\n'),
    meta: vi.fn(),
    report: vi.fn(),
    dashboard: vi.fn(),
  },
}));

const reportCalls: { key: string; filters: Record<string, unknown> }[] = [];
vi.mock('@/hooks/use-omnichannel-report', () => ({
  useOmnichannelReport: (_ws: string, key: string, filters: Record<string, unknown>) => {
    reportCalls.push({ key, filters });
    return {
      report: {
        reportKey: key,
        timezone: 'Asia/Kuala_Lumpur',
        range: { from: '2026-03-01', to: '2026-03-07' },
        granularity: 'day',
        buckets: [],
        series: [],
        rows: [],
        totals:
          key === 'responses'
            ? { sampleCount: 0, medianSeconds: null, p90Seconds: null, averageSeconds: null }
            : { opened: 0, closed: 0, reopened: 0 },
      },
      loading: false,
      error: false,
    };
  },
}));

beforeEach(() => {
  reportCalls.length = 0;
  vi.mocked(omnichannelReportService.exportReport).mockClear();
  window.history.replaceState(null, '', '/omnichannel/reports');
});

describe('Reports page - Export permission gate', () => {
  it('hides Export without reports.export (read-only role)', async () => {
    permissions = new Set(['reports.read']);
    render(<ReportsPage />);
    await waitFor(() => expect(screen.getByText('Conversations over time')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument();
  });

  it('shows Export with reports.export granted', async () => {
    permissions = new Set(['reports.read', 'reports.export']);
    render(<ReportsPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument());
  });

  it('renders the standard denial without reports.read', () => {
    permissions = new Set([]);
    render(<ReportsPage />);
    expect(screen.queryByRole('combobox', { name: 'Report' })).not.toBeInTheDocument();
  });
});

describe('Reports page - group-by is shared with Export (S-5)', () => {
  it('sends groupBy=user to the export once "By agent" is selected', async () => {
    permissions = new Set(['reports.read', 'reports.export']);
    window.history.replaceState(null, '', '/omnichannel/reports?report=responses&from=2026-03-01&to=2026-03-07');
    render(<ReportsPage />);

    await waitFor(() => expect(screen.getByText('Response time breakdown')).toBeInTheDocument());

    // Baseline: ungrouped export carries no groupBy.
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await waitFor(() => expect(omnichannelReportService.exportReport).toHaveBeenCalled());
    expect(vi.mocked(omnichannelReportService.exportReport).mock.calls[0][2].groupBy).toBeUndefined();

    fireEvent.click(screen.getByRole('combobox', { name: 'Group by' }));
    fireEvent.click(screen.getByText('By agent'));

    await waitFor(() =>
      expect(reportCalls.at(-1)).toEqual(expect.objectContaining({ key: 'responses', filters: expect.objectContaining({ groupBy: 'user' }) })),
    );

    vi.mocked(omnichannelReportService.exportReport).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await waitFor(() => expect(omnichannelReportService.exportReport).toHaveBeenCalled());
    const [wsId, reportKey, filters] = vi.mocked(omnichannelReportService.exportReport).mock.calls[0];
    expect(wsId).toBe('ws-1');
    expect(reportKey).toBe('responses');
    expect(filters.groupBy).toBe('user');
  });

  it('switching report keeps the shared filters and drops an unsupported group-by', async () => {
    permissions = new Set(['reports.read', 'reports.export']);
    window.history.replaceState(
      null,
      '',
      '/omnichannel/reports?report=responses&from=2026-03-01&to=2026-03-07&groupBy=user&granularity=day',
    );
    render(<ReportsPage />);
    await waitFor(() => expect(screen.getByText('Response time breakdown')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Report' }));
    fireEvent.click(screen.getByText('Conversations'));

    await waitFor(() => expect(screen.getByText('Conversations over time')).toBeInTheDocument());
    const last = reportCalls.at(-1);
    expect(last?.key).toBe('conversations');
    // Date range + granularity survive the report switch...
    expect(last?.filters).toEqual(
      expect.objectContaining({ from: '2026-03-01', to: '2026-03-07', granularity: 'day' }),
    );
    // ...but `groupBy=user` (unsupported by `conversations`) is dropped, so
    // the request can never 422 on a carried-over dimension.
    expect(last?.filters.groupBy).toBeUndefined();
    expect(new URLSearchParams(window.location.search).get('groupBy')).toBeNull();
  });
});

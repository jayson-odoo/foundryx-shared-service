/**
 * Reports page (plan 30, AC-RPT-47/52) - the Export control is gated
 * `reports.export` (UX only, `useCan` - the API is the real boundary); a
 * user holding `reports.read` but not `.export` must still see every report,
 * just no Export button.
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
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
      reports: [{ key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true }],
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
vi.mock('@/hooks/use-omnichannel-report', () => ({
  useOmnichannelReport: () => ({
    report: {
      reportKey: 'conversations',
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

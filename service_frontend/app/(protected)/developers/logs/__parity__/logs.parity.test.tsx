/**
 * Switch-off parity for the developer logs pages (Foundryx UIUX slice
 * W3-LOGS, build plan 1.3 and 4): the logs list, one log's Overview,
 * Trace and Payloads tabs, and the log retention settings page, rendered
 * with the switch OFF. Recorded on the code as it was before the slice; a
 * change that needs one of these snapshots updated is wrong by definition
 * (fix the code, never the snapshot). Generated ids are renamed in order of
 * appearance.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { IntegrationLogDetail, IntegrationLogItem } from '@/types/integration-logs';
import DeveloperLogsPage from '../page';
import DeveloperLogSettingsPage from '../settings/page';
import { LogDetailView } from '../components/log-detail-view';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/developers/logs'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { get: vi.fn(async () => ({ id: 'ws-1', name: 'Main desk' })) },
}));

const item = (over: Partial<IntegrationLogItem>): IntegrationLogItem => ({
  id: 'log-1',
  tenantId: 'ten-1',
  traceId: 'trc-7f3a',
  source: 'inbound_api',
  workspaceId: 'ws-1',
  apiKeyId: 'key-42',
  operation: 'POST /v1/messages',
  method: 'POST',
  status: 'success',
  statusCode: 202,
  errorCode: null,
  latencyMs: 118,
  externalRef: 'wamid.HBgM',
  createdAt: '2026-11-05T07:04:00Z',
  ...over,
});
const ROWS: IntegrationLogItem[] = [
  item({}),
  item({
    id: 'log-2',
    source: 'outbound_meta',
    operation: 'POST /messages',
    status: 'error',
    statusCode: 400,
    errorCode: 'template_paused',
    latencyMs: 61,
    workspaceId: null,
    createdAt: '2026-11-05T07:04:01Z',
  }),
  item({ id: 'log-3', source: 'webhook_delivery', operation: 'message.delivered', status: 'pending', statusCode: null, latencyMs: null, traceId: null }),
];
const DETAIL: IntegrationLogDetail = {
  ...ROWS[1],
  errorMessage: 'Template is paused by Meta.',
  requestSummary: { to: '60•••••789', template: 'promo_nov' },
  responseSummary: { error: { code: 132015 } },
};

vi.mock('@/services/integration-log-service', () => ({
  integrationLogService: {
    list: vi.fn(async () => ({ data: ROWS, total: ROWS.length, page: 0 })),
    export: vi.fn(async () => ''),
    get: vi.fn(async (id: string) => (id === DETAIL.id ? DETAIL : null)),
    getTrace: vi.fn(async () => ({ traceId: 'trc-7f3a', legs: [ROWS[0], ROWS[1]] })),
    getSettings: vi.fn(async () => ({ retentionDays: 30, isDefault: true })),
    updateSettings: vi.fn(),
  },
}));

/** Also masks React 19's `_r_N_` ids, in order of first appearance. */
function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('parity (switch off): developer logs', () => {
  it('list with rows', async () => {
    const { container } = render(
      <SettingsProvider>
        <DeveloperLogsPage />
      </SettingsProvider>,
    );
    await screen.findByText('message.delivered');
    expect(stable(container)).toMatchSnapshot();
  });

  it('one log: Overview, Trace and Payloads', async () => {
    const { container } = render(<LogDetailView logId="log-2" />, { wrapper: SettingsProvider });
    await screen.findByTestId('log-error');
    expect(stable(container)).toMatchSnapshot();

    fireEvent.mouseDown(screen.getByRole('tab', { name: /Trace/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Trace/ }));
    await screen.findByTestId('trace-timeline');
    expect(stable(container)).toMatchSnapshot();

    fireEvent.mouseDown(screen.getByRole('tab', { name: /Payloads/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Payloads/ }));
    await screen.findByText(/promo_nov/);
    expect(stable(container)).toMatchSnapshot();
  });

  it('log not found', async () => {
    const { container } = render(<LogDetailView logId="nope" />, { wrapper: SettingsProvider });
    await screen.findByText('Log not found.');
    expect(stable(container)).toMatchSnapshot();
  });

  it('log retention settings', async () => {
    const { container } = render(
      <SettingsProvider>
        <DeveloperLogSettingsPage />
      </SettingsProvider>,
    );
    await screen.findByDisplayValue('30');
    expect(stable(container)).toMatchSnapshot();
  });
});

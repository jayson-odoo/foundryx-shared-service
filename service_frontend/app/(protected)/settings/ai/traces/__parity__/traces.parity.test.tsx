/**
 * Switch-off parity for the AI traces pages (Foundryx UIUX slice W3-LOGS,
 * build plan 1.3 and 4): the traces list and one trace with its steps,
 * rendered with the switch OFF. Recorded on the code as it was before the
 * slice; a change that needs one of these snapshots updated is wrong by
 * definition (fix the code, never the snapshot). Generated ids are renamed
 * in order of appearance.
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AiTrace, AiTraceDetail } from '@/types/ai';
import AiTracesPage from '../page';
import { TraceDetailView } from '../../components/trace-detail-view';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/ai/traces'),
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

const trace = (over: Partial<AiTrace>): AiTrace => ({
  id: 'tr-1',
  conversationId: 'cv-1',
  agentId: 'ag-1',
  agentName: 'Reply helper',
  skillKey: 'reply.suggest',
  promptVersion: 3,
  provider: 'anthropic',
  model: 'claude-test-model',
  tokensIn: 812,
  tokensOut: 96,
  latencyMs: 1430,
  status: 'ok',
  error: null,
  flagged: false,
  spanCount: 2,
  createdAt: '2026-11-05T07:04:00Z',
  ...over,
});
const ROWS: AiTrace[] = [
  trace({}),
  trace({ id: 'tr-2', status: 'error', error: 'Provider timed out', flagged: true, agentName: 'Summariser', skillKey: null, promptVersion: null }),
];
const DETAIL: AiTraceDetail = {
  ...ROWS[0],
  spans: [
    {
      id: 'sp-1',
      parentId: null,
      dottedOrder: '1',
      spanKind: 'llm',
      name: 'llm',
      inputJson: { messages: [{ role: 'user', content: 'Where is my order?' }] },
      outputJson: { text: 'It ships today.', _truncated: true },
      tokensIn: 812,
      tokensOut: 96,
      latencyMs: 1400,
      status: 'ok',
      error: null,
      startedAt: '2026-11-05T07:04:00Z',
    },
    {
      id: 'sp-2',
      parentId: null,
      dottedOrder: '2',
      spanKind: 'tool',
      name: 'lookup_order',
      inputJson: null,
      outputJson: { found: false },
      tokensIn: 0,
      tokensOut: 0,
      latencyMs: 30,
      status: 'error',
      error: 'Order not found',
      startedAt: '2026-11-05T07:04:01Z',
    },
  ],
};

vi.mock('@/services/ai-service', () => ({
  aiService: {
    listTraces: vi.fn(async () => ({ data: ROWS, total: ROWS.length, page: 0 })),
    exportTraces: vi.fn(async () => ''),
    getTrace: vi.fn(async (id: string) => (id === DETAIL.id ? DETAIL : null)),
    flagTrace: vi.fn(),
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

describe('parity (switch off): AI traces', () => {
  it('list with rows', async () => {
    const { container } = render(
      <SettingsProvider>
        <AiTracesPage />
      </SettingsProvider>,
    );
    await screen.findByText('Summariser');
    expect(stable(container)).toMatchSnapshot();
  });

  it('one trace with its steps', async () => {
    const { container } = render(<TraceDetailView traceId="tr-1" />, { wrapper: SettingsProvider });
    await screen.findByText('Order not found');
    expect(stable(container)).toMatchSnapshot();
  });

  it('trace not found', async () => {
    const { container } = render(<TraceDetailView traceId="nope" />, { wrapper: SettingsProvider });
    await screen.findByText('Trace not found.');
    expect(stable(container)).toMatchSnapshot();
  });
});

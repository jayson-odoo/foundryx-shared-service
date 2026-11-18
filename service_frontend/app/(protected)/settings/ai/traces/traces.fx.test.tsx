/**
 * The AI traces pages with the Foundryx UIUX switch on (slice W3-LOGS).
 *
 * - Flag for review / Remove flag sends exactly what it sends with the
 *   switch off (requests captured at `apiFetch`, under the real service:
 *   same path, method and body). Its done toast has an Undo that puts each
 *   trace's flag back as it was, through the same endpoint.
 * - One trace is read-only: a page header with the way back to the traces,
 *   Hold to Copy on the agent, model, prompt key and time only; the steps'
 *   input and output blocks are unchanged and never copy.
 *
 * Switch off is pinned by `__parity__/traces.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import type { AiTrace, AiTraceDetail } from '@/types/ai';
import { TraceDetailView } from '../components/trace-detail-view';
import { useTracesListConfig } from '../components/use-traces-list-config';

const net = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchText: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch, apiFetchText: net.apiFetchText };
});

const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/ai/traces/tr-1'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

/** Every write sent: path, method and body. */
function writes() {
  return [...net.apiFetch.mock.calls, ...net.apiFetchText.mock.calls]
    .filter(([, init]) => init && (init as RequestInit).method && (init as RequestInit).method !== 'GET')
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

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
  spanCount: 1,
  createdAt: '2026-11-05T07:04:00Z',
  ...over,
});
const A = trace({});
const B = trace({ id: 'tr-2', flagged: true });
const DETAIL: AiTraceDetail = {
  ...A,
  spans: [
    {
      id: 'sp-1',
      parentId: null,
      dottedOrder: '1',
      spanKind: 'llm',
      name: 'llm',
      inputJson: { messages: [{ role: 'user', content: 'PROMPT-TEXT where is my order' }] },
      outputJson: { text: 'COMPLETION-TEXT' },
      tokensIn: 812,
      tokensOut: 96,
      latencyMs: 1400,
      status: 'ok',
      error: null,
      startedAt: '2026-11-05T07:04:00Z',
    },
  ],
};

beforeEach(() => {
  net.apiFetch.mockReset();
  net.apiFetchText.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') return A;
    if (path === '/ai/traces/tr-1') return DETAIL;
    return { data: [A, B], total: 2, page: 0 };
  });
});
afterEach(() => resetPageActionsForTests());

async function flagIn(on: boolean, rows: AiTrace[]) {
  const { result } = renderHook(() => useTracesListConfig(), { wrapper: look(on) });
  const flag = result.current.actions.find((a) => a.id === 'flag')!;
  const reload = vi.fn();
  await act(async () => {
    await runResourceAction(flag, rows, { reload });
  });
  return reload;
}

describe('flag: the same requests in both looks', () => {
  it('flag one, flag a mixed pair, remove from a flagged one', async () => {
    await flagIn(false, [A]);
    await flagIn(false, [A, B]);
    await flagIn(false, [B]);
    const off = writes();
    expect(off).toEqual([
      { path: '/ai/traces/tr-1/flag', method: 'POST', body: JSON.stringify({ flagged: true }) },
      { path: '/ai/traces/tr-1/flag', method: 'POST', body: JSON.stringify({ flagged: true }) },
      { path: '/ai/traces/tr-2/flag', method: 'POST', body: JSON.stringify({ flagged: true }) },
      { path: '/ai/traces/tr-2/flag', method: 'POST', body: JSON.stringify({ flagged: false }) },
    ]);

    net.apiFetch.mockClear();
    await flagIn(true, [A]);
    await flagIn(true, [A, B]);
    await flagIn(true, [B]);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone.mock.calls.map(([c]) => c.what)).toEqual([
      'Trace flagged for review',
      '2 traces flagged for review',
      'Flag removed from the trace',
    ]);
  });

  it('Undo puts each flag back as it was', async () => {
    const reload = await flagIn(true, [A, B]);
    const { undo, byWhom } = toasts.fxDone.mock.calls[0][0] as { undo: () => void; byWhom: string };
    expect(byWhom).toBe('Nurul Huda');
    net.apiFetch.mockClear();
    await act(async () => {
      undo();
      await new Promise((r) => setTimeout(r, 0));
    });
    // Only A changed (B was already flagged), so only A goes back.
    expect(writes()).toEqual([
      { path: '/ai/traces/tr-1/flag', method: 'POST', body: JSON.stringify({ flagged: false }) },
    ]);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});

describe('one trace under the switch', () => {
  it('page header, Hold to Copy on identifiers and the time only, steps unchanged', async () => {
    render(<TraceDetailView traceId="tr-1" />, { wrapper: look(true) });
    const input = await screen.findByText(/PROMPT-TEXT/);
    expect(screen.getByRole('heading', { level: 1, name: 'Reply helper' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'AI traces' })).toHaveAttribute('href', '/settings/ai/traces');

    const copyable = Array.from(document.querySelectorAll('[data-fx-h2c]')).map((el) => el.textContent);
    expect(copyable).toEqual(['Reply helper', 'claude-test-model', 'reply.suggest v3', '5 Nov 2026, 3:04 pm']);
    expect(input.tagName).toBe('PRE');
    expect(input.closest('[data-fx-h2c]')).toBeNull();
    expect(screen.getByText(/COMPLETION-TEXT/).closest('[data-fx-h2c]')).toBeNull();
    expect(writes()).toEqual([]);
  });
});

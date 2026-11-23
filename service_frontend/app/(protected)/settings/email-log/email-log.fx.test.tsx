/**
 * The email log pages with the Foundryx UIUX switch on (slice W3-LOGS).
 *
 * - Retry sends exactly what it sends with the switch off (requests captured
 *   at `apiFetch`, under the real service: same path, method and body), from
 *   the list's actions and from the email's red action. Its done toast names
 *   how many and by whom, never the recipient or subject, and has no Undo
 *   (nothing in the API takes a queued retry back).
 * - One email is read-only plain text with Hold to Copy on the template key,
 *   the connection id and the moments only. The body viewers are unchanged
 *   (same sandboxed frame and code blocks); only the view switch around them
 *   is the new sliding toggle.
 *
 * Switch off is pinned by `__parity__/email-log.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import type { EmailLogDetail } from '@/types/templates';
import { EmailDetailView } from './components/email-detail-view';
import { useEmailLogActions } from './components/use-email-log-actions';
import { useEmailLogListConfig } from './components/use-email-log-list-config';

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
  usePathname: vi.fn(() => '/settings/email-log/em-2'),
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
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));

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

const EMAIL: EmailLogDetail = {
  id: 'em-2',
  toEmail: 'kay@acme.test',
  subject: 'Your invoice',
  templateKey: 'billing.invoice',
  status: 'FAILED',
  attempts: 3,
  usedFallback: false,
  createdAt: '2026-11-05T07:04:00Z',
  sentAt: null,
  nextAttemptAt: null,
  htmlBody: '<p>Hello <b>Kay</b></p>',
  textBody: 'Hello Kay',
  lastError: 'SMTP 550 mailbox unavailable',
  connectionId: 'conn-9',
};
const OTHER = { ...EMAIL, id: 'em-5', toEmail: 'ali@acme.test', status: 'CANCELLED' as const };

beforeEach(() => {
  net.apiFetch.mockReset();
  net.apiFetchText.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') return { ...EMAIL, status: 'PENDING' };
    if (path === '/emails/em-2') return EMAIL;
    if (path.startsWith('/emails')) return { data: [EMAIL, OTHER], total: 2, page: 0 };
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

async function retryIn(on: boolean, rows: EmailLogDetail[]) {
  const { result } = renderHook(() => useEmailLogActions(), { wrapper: look(on) });
  const retry = result.current.find((a) => a.id === 'retry')!;
  const reload = vi.fn();
  await act(async () => {
    await runResourceAction(retry, rows, { reload });
  });
  expect(reload).toHaveBeenCalledTimes(1);
}

describe('retry: the same requests in both looks', () => {
  it('one email and several', async () => {
    await retryIn(false, [EMAIL]);
    await retryIn(false, [EMAIL, OTHER]);
    const off = writes();
    expect(off).toEqual([
      { path: '/emails/em-2/retry', method: 'POST', body: null },
      { path: '/emails/em-2/retry', method: 'POST', body: null },
      { path: '/emails/em-5/retry', method: 'POST', body: null },
    ]);
    expect(toasts.success).toHaveBeenCalledWith('Queued 1 email(s) for retry.');

    net.apiFetch.mockClear();
    await retryIn(true, [EMAIL]);
    await retryIn(true, [EMAIL, OTHER]);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenNthCalledWith(1, { what: 'Email queued for retry', byWhom: 'Nurul Huda' });
    expect(toasts.fxDone).toHaveBeenNthCalledWith(2, { what: '2 emails queued for retry', byWhom: 'Nurul Huda' });
    // No recipient, subject or body in any toast.
    const said = JSON.stringify(toasts.fxDone.mock.calls);
    expect(said).not.toMatch(/acme\.test|invoice|Hello/i);
  });

  it('the email red action sends the same retry', async () => {
    render(<EmailDetailView emailId="em-2" />, { wrapper: look(true) });
    await screen.findByTestId('email-last-error');
    const main = await waitFor(() => {
      const el = document.querySelector('[data-fx-main-action] button');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(main).toHaveAccessibleName('Retry');
    await act(async () => {
      fireEvent.click(main);
    });
    await waitFor(() => expect(writes()).toEqual([{ path: '/emails/em-2/retry', method: 'POST', body: null }]));
  });
});

describe('the email log list under the switch', () => {
  it('copies the template key only; recipients and subjects never copy', () => {
    const { result } = renderHook(() => useEmailLogListConfig(), { wrapper: look(true) });
    expect(result.current.fx?.copyable).toEqual(['templateKey']);
    expect(result.current.fx?.noun).toBe('emails');
  });
});

describe('one email under the switch', () => {
  it('plain text; Hold to Copy on identifiers and moments only', async () => {
    render(<EmailDetailView emailId="em-2" />, { wrapper: look(true) });
    const error = await screen.findByTestId('email-last-error');
    expect(error.closest('[data-fx-h2c]')).toBeNull();
    const copyable = Array.from(document.querySelectorAll('[data-fx-h2c]')).map((el) => el.textContent);
    expect(copyable).toEqual(['billing.invoice', '5 Nov 2026, 3:04 pm', 'conn-9']);
    expect(screen.getAllByText('kay@acme.test').every((el) => !el.closest('[data-fx-h2c]'))).toBe(true);
    expect(writes()).toEqual([]);
  });

  it('the body view switch is the sliding toggle; the viewers stay as they were', async () => {
    render(<EmailDetailView emailId="em-2" />, { wrapper: look(true) });
    await screen.findByTestId('email-last-error');
    fireEvent.mouseDown(screen.getByRole('tab', { name: /Body/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Body/ }));
    const frame = await screen.findByTestId('email-body-frame');
    expect(frame.getAttribute('sandbox')).toBe('allow-popups allow-popups-to-escape-sandbox');
    expect(frame.getAttribute('srcdoc')).toBe('<base target="_blank"><p>Hello <b>Kay</b></p>');
    expect(document.querySelector('[data-fx-toggle="single"]')).not.toBeNull();

    fireEvent.click(screen.getByTestId('body-view-html'));
    const html = await screen.findByText('<p>Hello <b>Kay</b></p>');
    expect(html.tagName).toBe('PRE');
    expect(html.closest('[data-fx-h2c]')).toBeNull();

    fireEvent.click(screen.getByTestId('body-view-text'));
    const text = await screen.findByText('Hello Kay');
    expect(text.tagName).toBe('PRE');
    expect(text.closest('[data-fx-h2c]')).toBeNull();
  });
});

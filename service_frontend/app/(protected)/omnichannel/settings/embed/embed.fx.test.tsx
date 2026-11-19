/**
 * Embed access with the Foundryx UIUX switch on (slice W2-WS): the signing
 * secret is write-only (shown once, in its own dialog, then forgotten), and
 * enabling, rotating and saving origins send exactly what they send with the
 * switch off. Switch off is pinned by `__parity__/embed.parity.test.tsx`.
 * Requests are captured at `apiFetch`, under the real service.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type { EmbedConfig } from '@/services/embed-config-service';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { PageHeader } from '@/components/platform/page-header';
import { EmbedAccessPanel } from './embed-access-panel';
import { fxOriginsCount } from './fx-origins-editor';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/embed'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

const SECRET = 'emb_secret_shown_once_abc123';
let state: EmbedConfig;

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <PageHeader title="Embed access" />
        {children}
      </FxProvider>
    );
  };
}

function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method)
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem('fx_settings', JSON.stringify({ hold: false }));
  state = {
    connectionId: 'conn-embed-1',
    allowedOrigins: ['https://crm.acme.com'],
    hasSecret: true,
    host: 'https://api.example.com',
    workspaces: [{ id: 'ws-general', name: 'General' }],
  };
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/enable')) {
      state = { ...state, connectionId: 'conn-embed-1' };
      return { ...state };
    }
    if (path.endsWith('/rotate-secret')) return { embedSecret: SECRET };
    if (path.endsWith('/origins')) {
      state = {
        ...state,
        allowedOrigins: JSON.parse(String(init?.body)).allowedOrigins,
      };
      return { ...state };
    }
    return { ...state };
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});
afterEach(() => resetPageActionsForTests());

async function rotateIn(on: boolean) {
  const view = render(<EmbedAccessPanel />, { wrapper: look(on) });
  fireEvent.click(
    await screen.findByRole('button', {
      name: on ? 'Replace' : 'Rotate secret',
    }),
  );
  fireEvent.click(
    await screen.findByRole('button', {
      name: on ? 'Rotate secret' : 'Rotate',
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByLabelText(on ? 'Embed secret' : 'embed secret'),
    ).toHaveValue(SECRET),
  );
  return view;
}

async function saveOriginsIn(on: boolean) {
  const view = render(<EmbedAccessPanel />, { wrapper: look(on) });
  fireEvent.mouseDown(
    await screen.findByRole('tab', { name: /Allowed origins/ }),
  );
  fireEvent.click(screen.getByRole('tab', { name: /Allowed origins/ }));
  const input = await screen.findByLabelText('New allowed origin');
  fireEvent.change(input, { target: { value: 'https://app.acme.com' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  fireEvent.click(
    screen.getByRole('button', { name: 'Remove https://crm.acme.com' }),
  );
  fireEvent.click(
    screen.getByRole('button', { name: /Save origins|Save 1 origin/ }),
  );
  await waitFor(() => expect(writes()).toHaveLength(1));
  return view;
}

describe('the same requests in both looks', () => {
  it('rotate secret', async () => {
    (await rotateIn(false)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    await rotateIn(true);
    expect(off).toEqual([
      {
        path: '/omnichannel/embed-config/rotate-secret',
        method: 'POST',
        body: null,
      },
    ]);
    expect(writes()).toEqual(off);
  });

  it('save origins', async () => {
    (await saveOriginsIn(false)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    state.allowedOrigins = ['https://crm.acme.com'];
    await saveOriginsIn(true);
    expect(off).toHaveLength(1);
    expect(off[0].body).toBe('{"allowedOrigins":["https://app.acme.com"]}');
    expect(writes()).toEqual(off);
  });

  it('enable embed access', async () => {
    state.connectionId = null;
    const offView = render(<EmbedAccessPanel />, { wrapper: look(false) });
    fireEvent.click(
      await screen.findByRole('button', { name: 'Enable embed access' }),
    );
    await waitFor(() => expect(writes()).toHaveLength(1));
    const off = writes();
    offView.unmount();
    net.apiFetch.mockClear();
    state.connectionId = null;
    render(<EmbedAccessPanel />, { wrapper: look(true) });
    // The page header's red action.
    fireEvent.click(
      await screen.findByRole('button', { name: 'Enable embed access' }),
    );
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Embed access enabled',
      byWhom: 'Nurul Huda',
    });
  });
});

describe('the signing secret under the new look', () => {
  it('a saved secret reads "Saved" and never shows a value', async () => {
    render(<EmbedAccessPanel />, { wrapper: look(true) });
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/•/)).not.toBeInTheDocument();
  });

  it('rotating asks first and says what stops working', async () => {
    render(<EmbedAccessPanel />, { wrapper: look(true) });
    fireEvent.click(await screen.findByRole('button', { name: 'Replace' }));
    expect(
      await screen.findByText('Rotate the embed secret?'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Assertions signed with the old secret will fail at once/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Keep current secret' }),
    ).toHaveFocus();
  });

  it('the new secret shows once in its dialog and is gone after Done', async () => {
    await rotateIn(true);
    expect(
      screen.getByText("Copy it now. It won't be shown again."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() =>
      expect(screen.queryByLabelText('Embed secret')).not.toBeInTheDocument(),
    );
    expect(document.documentElement.outerHTML).not.toContain(SECRET);
    expect(screen.getByText('Saved')).toBeInTheDocument();
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        expect(store.getItem(store.key(i) ?? '') ?? '').not.toContain(SECRET);
      }
    }
  });
});

describe('allowed origins under the new look', () => {
  it('Save origins is greyed with "Nothing changed yet." until the list changes', async () => {
    render(<EmbedAccessPanel />, { wrapper: look(true) });
    fireEvent.mouseDown(
      await screen.findByRole('tab', { name: /Allowed origins/ }),
    );
    fireEvent.click(screen.getByRole('tab', { name: /Allowed origins/ }));
    expect(await screen.findByText('Nothing changed yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save origins' }));
    expect(writes()).toHaveLength(0);
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove https://crm.acme.com' }),
    );
    expect(screen.queryByText('Nothing changed yet.')).not.toBeInTheDocument();
  });

  it('a wrong origin says why under the field', async () => {
    render(<EmbedAccessPanel />, { wrapper: look(true) });
    fireEvent.mouseDown(
      await screen.findByRole('tab', { name: /Allowed origins/ }),
    );
    fireEvent.click(screen.getByRole('tab', { name: /Allowed origins/ }));
    const input = await screen.findByLabelText('New allowed origin');
    fireEvent.change(input, { target: { value: 'not a url' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(document.querySelector('[data-fx-message="error"]')).not.toBeNull();
  });

  it('the done toast counts the origins and Undo saves the old list back', async () => {
    await saveOriginsIn(true);
    const call = toasts.fxDone.mock.calls[0][0] as {
      what: string;
      howMany: string;
      undo: () => void;
    };
    expect(call.what).toBe('Allowed origins saved');
    expect(call.howMany).toBe('1 origin');
    net.apiFetch.mockClear();
    call.undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toBe(
      '{"allowedOrigins":["https://crm.acme.com"]}',
    );
    expect(fxOriginsCount(3)).toBe('3 origins');
  });
});

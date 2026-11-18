/**
 * Workspaces with the Foundryx UIUX switch on (slice W2-WS): the API key is
 * shown once and then gone from the page, storage, logs and toasts; minting,
 * revoking, creating, saving and trashing send exactly what they send with
 * the switch off. Switch off is pinned by `__parity__/workspaces.parity.test.tsx`.
 *
 * Requests are captured at `apiFetch`, under the real services, so "the same
 * request" means the same path, method and body.
 */
import type { ReactNode } from 'react';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ApiKeyItem } from '@/types/api-keys';
import type { Workspace } from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { Form } from '@/components/ui/form';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { fxMintLabel } from './components/fx-mint-api-key-dialog';
import { fxRevokeLine } from './components/fx-revoke-api-key-dialog';
import { MintApiKeyDialog } from './components/mint-api-key-dialog';
import { RevokeApiKeyDialog } from './components/revoke-api-key-dialog';
import { useApiKeyList } from './components/use-api-key-list';
import { useWorkspaceActions } from './components/use-workspace-actions';
import { useWorkspaceForm } from './components/use-workspace-form';
import { SettingsTab } from './components/workspace-form-fields';

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
  usePathname: vi.fn(() => '/omnichannel/settings/workspaces'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: () => true,
    ready: true,
    permissions: new Set<string>(),
  }),
}));
vi.mock('./components/use-business-hours', () => ({
  useBusinessHours: () => ({
    isLoading: false,
    timezone: 'UTC',
    windows: { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] },
    isDirty: false,
    isSaving: false,
    saveError: null,
    fieldErrors: {},
    setTimezone: vi.fn(),
    setWindows: vi.fn(),
    save: vi.fn(async () => true),
    discard: vi.fn(),
  }),
}));

const FULL_KEY = 'fxw_live_abcd1234thisisthesecrettail';
const KEY: ApiKeyItem = {
  id: 'key-1',
  workspaceId: 'wsp-1',
  name: 'Production server',
  keyPrefix: 'abcd1234',
  maskedKey: 'fxw_live_abcd1234••••',
  status: 'ACTIVE',
  lastUsedAt: null,
  revokedAt: null,
  createdAt: '2026-11-01T02:00:00Z',
  webhookEndpointCount: 0,
};
const WS: Workspace = {
  id: 'wsp-1',
  tenantId: 'ten-1',
  name: 'General',
  status: 'ACTIVE',
  channelCount: 0,
  memberCount: 0,
  isDefault: false,
  isTrashed: false,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        {children}
      </FxProvider>
    );
  };
}

/** Every write the page sent: path, method and body. */
function writes() {
  return net.apiFetch.mock.calls
    .filter(
      ([, init]) =>
        init &&
        (init as RequestInit).method &&
        (init as RequestInit).method !== 'GET',
    )
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
  // Single-click confirms, so a test needs no 3 s hold.
  window.localStorage.setItem('fx_settings', JSON.stringify({ hold: false }));
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/api-keys') && init?.method === 'POST')
      return { key: KEY, fullKey: FULL_KEY };
    if (path === '/omnichannel/workspaces' && init?.method === 'POST') {
      return { ...WS, id: 'wsp-new', name: JSON.parse(String(init.body)).name };
    }
    if (
      path.startsWith('/omnichannel/workspaces/wsp-1') &&
      init?.method === 'PATCH'
    ) {
      return { ...WS, ...JSON.parse(String(init.body)) };
    }
    if (path.startsWith('/omnichannel/workspaces/wsp-1')) return WS;
    return {};
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});
afterEach(() => resetPageActionsForTests());

async function mintIn(on: boolean) {
  const onOpenChange = vi.fn();
  const view = render(
    <MintApiKeyDialog
      workspaceId="wsp-1"
      open
      onOpenChange={onOpenChange}
      onMinted={vi.fn()}
    />,
    { wrapper: look(on) },
  );
  fireEvent.change(screen.getByLabelText('Key name'), {
    target: { value: '  Production server ' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Mint/ }));
  await waitFor(() =>
    expect(screen.getByLabelText('API key')).toHaveValue(FULL_KEY),
  );
  return { ...view, onOpenChange };
}

describe('mint: the same request in both looks', () => {
  it('posts the same name to the same endpoint', async () => {
    (await mintIn(false)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    await mintIn(true);
    const on = writes();
    expect(off).toEqual([
      {
        path: '/omnichannel/workspaces/wsp-1/api-keys',
        method: 'POST',
        body: '{"name":"Production server"}',
      },
    ]);
    expect(on).toEqual(off);
  });
});

describe('mint under the new look: the key is shown once', () => {
  it('shows the key with Copy and the warning, then forgets it after Done', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map(
      (m) => vi.spyOn(console, m).mockImplementation(() => {}),
    );
    const { rerender } = await mintIn(true);
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    expect(
      screen.getByText("Copy it now. It won't be shown again."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    // The parent closes the dialog on Done.
    rerender(
      <MintApiKeyDialog
        workspaceId="wsp-1"
        open={false}
        onOpenChange={vi.fn()}
        onMinted={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByLabelText('API key')).not.toBeInTheDocument(),
    );

    expect(document.documentElement.outerHTML).not.toContain(FULL_KEY);
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        expect(store.getItem(store.key(i) ?? '') ?? '').not.toContain(FULL_KEY);
      }
    }
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(FULL_KEY);
      spy.mockRestore();
    }
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'API key Production server minted',
      byWhom: 'Nurul Huda',
    });
    expect(JSON.stringify(toasts.fxDone.mock.calls)).not.toContain(FULL_KEY);

    // Opening it again starts from an empty name, never the old key.
    rerender(
      <MintApiKeyDialog
        workspaceId="wsp-1"
        open
        onOpenChange={vi.fn()}
        onMinted={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Key name')).toHaveValue('');
    expect(document.documentElement.outerHTML).not.toContain(FULL_KEY);
  });

  it('a refused mint says why under the action, not as a toast', async () => {
    net.apiFetch.mockRejectedValueOnce(new Error('boom'));
    render(
      <MintApiKeyDialog
        workspaceId="wsp-1"
        open
        onOpenChange={vi.fn()}
        onMinted={vi.fn()}
      />,
      {
        wrapper: look(true),
      },
    );
    fireEvent.change(screen.getByLabelText('Key name'), {
      target: { value: 'Production server' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Mint/ }));
    expect(
      await screen.findByText("Couldn't mint the key. Try again."),
    ).toBeInTheDocument();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it('with no name the red action is greyed with its reason and sends nothing', () => {
    render(
      <MintApiKeyDialog
        workspaceId="wsp-1"
        open
        onOpenChange={vi.fn()}
        onMinted={vi.fn()}
      />,
      {
        wrapper: look(true),
      },
    );
    expect(screen.getByText('Enter a key name.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Mint key/ }));
    expect(net.apiFetch).not.toHaveBeenCalled();
    expect(fxMintLabel(' Production server ')).toBe(
      'Mint Production server key',
    );
  });
});

describe('revoke a key with endpoints: the same choice in both looks', () => {
  async function choose(on: boolean, untick: boolean) {
    const onConfirm = vi.fn();
    const view = render(
      <RevokeApiKeyDialog
        keyName="Order sync"
        endpointCount={3}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
      { wrapper: look(on) },
    );
    if (on)
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: 'Revoke key' }),
        ).toBeInTheDocument(),
      );
    if (untick) fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(
      screen.getByRole('button', { name: on ? 'Revoke key' : 'Revoke' }),
    );
    view.unmount();
    return onConfirm.mock.calls;
  }

  it('pause on and off reach the same answer', async () => {
    expect(await choose(true, false)).toEqual(await choose(false, false));
    expect(await choose(true, true)).toEqual(await choose(false, true));
    expect(await choose(true, true)).toEqual([[false]]);
  });

  it('reads as a playbook confirm with the safe button focused', async () => {
    render(
      <RevokeApiKeyDialog
        keyName="Order sync"
        endpointCount={3}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
      {
        wrapper: look(true),
      },
    );
    expect(await screen.findByText('Revoke Order sync?')).toBeInTheDocument();
    expect(screen.getByText(fxRevokeLine(3))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep key' })).toHaveFocus();
    expect(fxRevokeLine(1)).toBe(
      '1 webhook endpoint uses this key. It stops working at once.',
    );
  });

  it('a key with no endpoints parks the same deferred revoke, named for the countdown', () => {
    const off = renderHook(() => useApiKeyList('wsp-1', vi.fn(), vi.fn()), {
      wrapper: look(false),
    });
    const on = renderHook(() => useApiKeyList('wsp-1', vi.fn(), vi.fn()), {
      wrapper: look(true),
    });
    const pick = (a: (typeof off.result.current.config.actions)[number]) => ({
      id: a.id,
      actionKey: a.deferred?.actionKey,
      entityType: a.deferred?.entityType,
      payload: a.deferred?.payload,
    });
    expect(on.result.current.config.actions.map(pick)).toEqual(
      off.result.current.config.actions.map(pick),
    );
    expect(on.result.current.config.actions[0].deferred?.fxName?.([KEY])).toBe(
      'Production server',
    );
  });
});

describe('workspace record: the same requests in both looks', () => {
  async function saveIn(on: boolean, id: string | undefined) {
    net.apiFetch.mockClear();
    const { result } = renderHook(() => useWorkspaceForm(id, !id), {
      wrapper: look(on),
    });
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => {
      result.current.form.setValue('name', 'Sales', { shouldDirty: true });
      result.current.form.setValue('status', 'INACTIVE', { shouldDirty: true });
    });
    await act(async () => {
      await result.current.config!.onSave();
    });
    return writes();
  }

  it('create and save send the same bodies', async () => {
    const createOff = await saveIn(false, undefined);
    const createOn = await saveIn(true, undefined);
    expect(createOff).toEqual([
      {
        path: '/omnichannel/workspaces',
        method: 'POST',
        body: '{"name":"Sales","status":"INACTIVE"}',
      },
    ]);
    expect(createOn).toEqual(createOff);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Workspace Sales created',
      byWhom: 'Nurul Huda',
    });

    const saveOff = await saveIn(false, 'wsp-1');
    const saveOn = await saveIn(true, 'wsp-1');
    expect(saveOff).toHaveLength(1);
    expect(saveOn).toEqual(saveOff);
  });

  it('Trash parks the same deferred action in both looks, named for the countdown', () => {
    const off = renderHook(() => useWorkspaceActions(), {
      wrapper: look(false),
    });
    const on = renderHook(() => useWorkspaceActions(), { wrapper: look(true) });
    const trash = (list: typeof off.result.current) =>
      list.find((a) => a.id === 'trash')!;
    expect(trash(on.result.current).deferred?.actionKey).toBe(
      trash(off.result.current).deferred?.actionKey,
    );
    expect(trash(on.result.current).deferred?.entityType).toBe('workspace');
    expect(trash(on.result.current).deferred?.fxName?.([WS])).toBe('General');
    expect(trash(on.result.current).confirm).toBeUndefined();
  });
});

describe('workspace settings fields are named under the new look only', () => {
  function Fields() {
    const form = useForm<{ name: string; status: 'ACTIVE' | 'INACTIVE' }>({
      defaultValues: { name: 'General', status: 'ACTIVE' },
    });
    return (
      <Form {...form}>
        <SettingsTab form={form} editing creating={false} workspace={WS} />
      </Form>
    );
  }

  it('adds the names with the switch on and nothing with it off', () => {
    const off = render(<Fields />, { wrapper: look(false) });
    expect(
      off.container.querySelector('[aria-label="Workspace name"]'),
    ).toBeNull();
    expect(off.container.querySelector('[aria-label="Status"]')).toBeNull();
    off.unmount();
    render(<Fields />, { wrapper: look(true) });
    expect(screen.getByRole('textbox', { name: 'Workspace name' })).toHaveValue(
      'General',
    );
    expect(
      screen.getByRole('combobox', { name: 'Status' }),
    ).toBeInTheDocument();
  });
});

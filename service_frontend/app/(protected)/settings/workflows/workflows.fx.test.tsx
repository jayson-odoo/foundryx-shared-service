/**
 * Settings > Workflows and Settings > Imports with the Foundryx UIUX switch
 * on (slice W4-SETTINGS): the red action sends exactly what today's Save
 * button sends for the same input; steppers hold whole numbers inside
 * today's ranges; Undo only where the earlier value was the workspace's own.
 * Switch off is pinned by the pages' `__parity__` tests. Requests are
 * captured at `apiFetch`, under the real services.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import WorkflowSettingsPage from './page';
import ImportSettingsPage from '../imports/page';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/workflows'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Nurul Huda', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

const stored = vi.hoisted(() => ({
  workflow: { runRetentionDays: 90, isDefault: true },
  imports: { maxRows: 50000, maxFileMb: 25, isDefault: false },
}));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <SettingsProvider>
        <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
          {children}
        </FxProvider>
      </SettingsProvider>
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

function typeInto(el: HTMLElement, value: string) {
  fireEvent.change(el, { target: { value } });
  fireEvent.blur(el);
}

beforeEach(() => {
  stored.workflow = { runRetentionDays: 90, isDefault: true };
  stored.imports = { maxRows: 50000, maxFileMb: 25, isDefault: false };
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (path === '/workflows/settings') {
      return body ? { runRetentionDays: body.runRetentionDays, isDefault: false } : stored.workflow;
    }
    if (path === '/imports/settings') {
      return body ? { ...stored.imports, ...body, isDefault: false } : stored.imports;
    }
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

describe('Workflows: the same save in both looks', () => {
  it.each([['30'], ['3650'], ['1']])('retention %s days', async (days) => {
    const off = render(<WorkflowSettingsPage />, { wrapper: look(false) });
    typeInto(await screen.findByDisplayValue('90'), days);
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const sent = writes();
    off.unmount();
    net.apiFetch.mockClear();
    resetPageActionsForTests();

    render(<WorkflowSettingsPage />, { wrapper: look(true) });
    typeInto(await screen.findByLabelText('Keep run history for'), days);
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual(sent);
  });

  it('a typed value outside today\'s range or with decimals is held to a whole day inside it', async () => {
    render(<WorkflowSettingsPage />, { wrapper: look(true) });
    const field = await screen.findByLabelText('Keep run history for');
    typeInto(field, '9999');
    expect(field).toHaveValue('3650');
    typeInto(field, '14.6');
    expect(field).toHaveValue('15');
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toBe(JSON.stringify({ runRetentionDays: 15 }));
  });

  it('no Undo when the earlier retention was the deployment default', async () => {
    render(<WorkflowSettingsPage />, { wrapper: look(true) });
    typeInto(await screen.findByLabelText('Keep run history for'), '30');
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow settings' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    expect(toasts.fxDone.mock.calls[0][0]).toMatchObject({
      what: 'Run history kept for 30 days',
      byWhom: 'Nurul Huda',
      undo: undefined,
    });
  });

  it('Undo writes a custom earlier retention back', async () => {
    stored.workflow = { runRetentionDays: 120, isDefault: false };
    render(<WorkflowSettingsPage />, { wrapper: look(true) });
    typeInto(await screen.findByLabelText('Keep run history for'), '30');
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow settings' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const first = writes()[0];
    net.apiFetch.mockClear();
    toasts.fxDone.mock.calls[0][0].undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].path).toBe(first.path);
    expect(writes()[0].method).toBe(first.method);
    expect(writes()[0].body).toBe(JSON.stringify({ runRetentionDays: 120 }));
  });
});

describe('Imports: the same save in both looks', () => {
  it.each([
    ['1000', '10'],
    ['1000000', '1024'],
    ['50000', '25'],
  ])('rows %s, %s MB', async (rows, mb) => {
    const off = render(<ImportSettingsPage />, { wrapper: look(false) });
    typeInto(await screen.findByDisplayValue('50000'), rows);
    typeInto(screen.getByDisplayValue('25'), mb);
    fireEvent.click(screen.getByRole('button', { name: 'Save import settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const sent = writes();
    off.unmount();
    net.apiFetch.mockClear();
    resetPageActionsForTests();

    render(<ImportSettingsPage />, { wrapper: look(true) });
    typeInto(await screen.findByLabelText('Max rows per import'), rows);
    typeInto(screen.getByLabelText('Max file size'), mb);
    fireEvent.click(screen.getByRole('button', { name: 'Save import settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual(sent);
  });

  it('Undo writes the earlier custom caps back', async () => {
    render(<ImportSettingsPage />, { wrapper: look(true) });
    typeInto(await screen.findByLabelText('Max file size'), '50');
    fireEvent.click(screen.getByRole('button', { name: 'Save import settings' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    expect(toasts.fxDone.mock.calls[0][0].what).toBe('Import limits saved');
    net.apiFetch.mockClear();
    toasts.fxDone.mock.calls[0][0].undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toBe(JSON.stringify({ maxRows: 50000, maxFileMb: 25 }));
  });
});

/**
 * My Account with the Foundryx UIUX switch on (slice W4-ACCOUNT): every write
 * sends exactly what the switch-off page sends for the same input (profile
 * save, time zone, change-email request and cancel, avatar remove), Undo
 * sends the earlier value back, and the current password is never kept,
 * shown, toasted, logged or stored after it is sent. Switch off is pinned by
 * `__parity__/account.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { __resetAccountNameOverride } from './components/use-account-form';
import { fxPendingWords } from './components/fx-account-profile-tab';
import { fxZoneCity } from './components/fx-timezone-card';
import Page from './page';

const PASSWORD = 'Tr0ub4dor&3-secret';

const svc = vi.hoisted(() => ({
  getPending: vi.fn(),
  request: vi.fn(),
  cancel: vi.fn(),
  identity: vi.fn(),
  updateProfile: vi.fn(),
  saveTimezone: vi.fn(),
  removeSelf: vi.fn(),
  uploadSelf: vi.fn(),
  sessionUpdate: vi.fn(),
  session: { avatar: null as string | null, timezone: null as string | null },
}));
const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));

vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('@/lib/datetime', async (orig) => ({
  ...((await orig()) as object),
  browserTimeZone: () => 'Asia/Kuala_Lumpur',
}));
vi.mock('@/services/auth-service', () => ({
  AuthError: class AuthError extends Error {},
  authService: { signin: vi.fn(), identity: svc.identity },
}));
vi.mock('@/services/account-service', () => ({
  accountService: { updateProfile: (input: unknown) => svc.updateProfile(input) },
}));
vi.mock('@/services/profile-preferences-service', () => ({
  profilePreferencesService: { saveTimezone: (tz: string | null) => svc.saveTimezone(tz) },
}));
vi.mock('@/services/avatar-service', () => ({
  avatarService: {
    uploadSelf: (blob: Blob) => svc.uploadSelf(blob),
    removeSelf: (...args: unknown[]) => svc.removeSelf(...args),
  },
}));
vi.mock('@/services/email-change-service', () => {
  class InvalidPasswordError extends Error {}
  class RateLimitError extends Error {
    retryAfterSeconds: number | null = null;
  }
  return {
    InvalidPasswordError,
    InvalidTokenError: class extends Error {},
    EmailTakenError: class extends Error {},
    RateLimitError,
    emailChangeService: {
      getPending: () => svc.getPending(),
      request: (...args: unknown[]) => svc.request(...args),
      cancel: (...args: unknown[]) => svc.cancel(...args),
      approve: vi.fn(),
      verify: vi.fn(),
    },
  };
});
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    update: svc.sessionUpdate,
    data: {
      user: {
        id: '1',
        name: 'Demo User',
        email: 'demo@example.com',
        roles: [{ id: 'r1', name: 'Admin' }],
        permissions: [],
        avatar: svc.session.avatar,
        timezone: svc.session.timezone,
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/account',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <SettingsProvider>
        <TooltipsProvider>
          <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
            {children}
          </FxProvider>
        </TooltipsProvider>
      </SettingsProvider>
    );
  };
}

const PENDING = {
  newEmail: 'new@example.com',
  status: 'PENDING_OLD' as const,
  expiresAt: '2026-11-20T00:00:00Z',
  createdAt: '2026-11-19T00:00:00Z',
};

beforeEach(() => {
  __resetAccountNameOverride();
  svc.session.avatar = null;
  svc.session.timezone = null;
  svc.getPending.mockReset().mockResolvedValue(null);
  svc.request.mockReset().mockResolvedValue(PENDING);
  svc.cancel.mockReset().mockResolvedValue(undefined);
  svc.updateProfile.mockReset().mockImplementation(async (input: unknown) => input);
  svc.saveTimezone.mockReset().mockResolvedValue(undefined);
  svc.removeSelf.mockReset().mockResolvedValue({ avatar: null });
  svc.uploadSelf.mockReset();
  svc.sessionUpdate.mockReset().mockResolvedValue(null);
  svc.identity.mockReset().mockResolvedValue({
    email: 'demo@example.com',
    name: 'Demo User',
    avatar: null,
    roles: [{ id: 'r1', name: 'Admin' }],
    permissions: [],
    isPlatformTenant: false,
  });
  Object.values(toasts).forEach((fn) => fn.mockReset());
});
afterEach(() => {
  resetPageActionsForTests();
  document.cookie = 'fx_uiux=; Max-Age=0; path=/';
});

async function openPage(on: boolean) {
  const user = userEvent.setup();
  const view = render(<Page />, { wrapper: look(on) });
  await screen.findAllByText('Demo User');
  await waitFor(() => expect(svc.getPending).toHaveBeenCalled());
  return { user, view };
}

/** Runs `act` in the switch-off look, then the switch-on look; returns both calls. */
async function bothLooks(
  spy: ReturnType<typeof vi.fn>,
  act: (on: boolean, user: ReturnType<typeof userEvent.setup>) => Promise<void>,
) {
  const calls: unknown[][] = [];
  for (const on of [false, true]) {
    spy.mockClear();
    __resetAccountNameOverride();
    resetPageActionsForTests();
    const { user, view } = await openPage(on);
    await act(on, user);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    calls.push(spy.mock.calls[0]);
    view.unmount();
  }
  return calls;
}

async function openChangeEmail(on: boolean, user: ReturnType<typeof userEvent.setup>) {
  if (on) {
    await user.click(await screen.findByRole('button', { name: 'Change email' }));
  } else {
    await user.click(await screen.findByRole('button', { name: /^actions$/i }));
    await user.click(await screen.findByRole('menuitem', { name: /change email/i }));
  }
  return screen.findByRole('dialog');
}

describe('the same writes in both looks', () => {
  it.each([
    ['a new name', 'Nurul Huda'],
    ['a padded name (trimmed in both)', '  Siti Aminah  '],
  ])('profile save: %s', async (_n, typed) => {
    const [off, on] = await bothLooks(svc.updateProfile, async (fx, user) => {
      await user.click(await screen.findByRole('button', { name: fx ? 'Edit profile' : /^edit$/i }));
      const field = await screen.findByPlaceholderText('Full name');
      await user.clear(field);
      await user.type(field, typed);
      await user.click(screen.getByRole('button', { name: fx ? 'Save profile' : /^save/i }));
    });
    expect(on).toEqual(off);
    expect(on).toEqual([{ name: typed.trim() }]);
  });

  it('time zone: picking a zone', async () => {
    const [off, on] = await bothLooks(svc.saveTimezone, async (fx, user) => {
      await user.click(screen.getByRole('combobox', { name: fx ? 'Time zone' : 'Timezone' }));
      await user.type(await screen.findByPlaceholderText(fx ? 'Search time zones' : /Search timezones/), 'Tokyo');
      await user.click(await screen.findByRole('option', { name: /Asia\/Tokyo/ }));
    });
    expect(on).toEqual(off);
    expect(on).toEqual(['Asia/Tokyo']);
  });

  it('time zone: back to the device zone sends null', async () => {
    svc.session.timezone = 'Asia/Tokyo';
    const [off, on] = await bothLooks(svc.saveTimezone, async (fx, user) => {
      await user.click(screen.getByRole('combobox', { name: fx ? 'Time zone' : 'Timezone' }));
      await user.click(
        await screen.findByRole('option', { name: fx ? /This device's zone/ : /Browser default/ }),
      );
    });
    expect(on).toEqual(off);
    expect(on).toEqual([null]);
  });

  it('change email: the same address and password go to the same request', async () => {
    const [off, on] = await bothLooks(svc.request, async (fx, user) => {
      const dialog = await openChangeEmail(fx, user);
      await user.type(within(dialog).getByLabelText('New email'), 'new@example.com');
      await user.type(within(dialog).getByLabelText('Current password'), PASSWORD);
      await user.click(within(dialog).getByRole('button', { name: 'Send approval link' }));
    });
    expect(on).toEqual(off);
    expect(on).toEqual(['new@example.com', PASSWORD]);
  });

  it('cancelling a waiting email change', async () => {
    svc.getPending.mockResolvedValue(PENDING);
    const [off, on] = await bothLooks(svc.cancel, async (fx, user) => {
      await user.click(
        await screen.findByRole('button', { name: fx ? 'Cancel email change' : 'Cancel request' }),
      );
    });
    expect(on).toEqual(off);
  });

  it('removing the photo', async () => {
    // The own-avatar hook keeps the last result in module state, so each look
    // gets fresh modules (and its own providers from them).
    svc.session.avatar = 'https://cdn.example/a.png';
    const calls: unknown[][] = [];
    for (const on of [false, true]) {
      vi.resetModules();
      const { default: FreshPage } = await import('./page');
      const { FxProvider: P } = await import('@/providers/fx-provider');
      const { SettingsProvider: SP } = await import('@/providers/settings-provider');
      const { TooltipsProvider: TP } = await import('@/providers/tooltips-provider');
      svc.removeSelf.mockClear();
      const user = userEvent.setup();
      const view = render(
        <SP>
          <TP>
            <P initial={on} initialTheme={FX_DEFAULT_THEME}>
              <FreshPage />
            </P>
          </TP>
        </SP>,
      );
      await user.click(await screen.findByRole('button', { name: 'Edit avatar' }));
      await user.click(await screen.findByRole('menuitem', { name: /remove photo/i }));
      await waitFor(() => expect(svc.removeSelf).toHaveBeenCalledTimes(1));
      calls.push(svc.removeSelf.mock.calls[0]);
      view.unmount();
    }
    expect(calls[1]).toEqual(calls[0]);
  });
});

describe('done toasts and Undo (switch on)', () => {
  it('a name change says the new name; Undo sends the earlier one', async () => {
    const { user } = await openPage(true);
    await user.click(await screen.findByRole('button', { name: 'Edit profile' }));
    const field = await screen.findByPlaceholderText('Full name');
    await user.clear(field);
    await user.type(field, 'Nurul Huda');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('Name changed to Nurul Huda');
    svc.updateProfile.mockClear();
    done.undo();
    await waitFor(() => expect(svc.updateProfile).toHaveBeenCalledWith({ name: 'Demo User' }));
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it('a time zone says where; Undo saves the earlier choice', async () => {
    const { user } = await openPage(true);
    expect(screen.getByText(/^Kuala Lumpur time \(GMT\+8\)$/)).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Time zone' }));
    await user.type(await screen.findByPlaceholderText('Search time zones'), 'Tokyo');
    await user.click(await screen.findByRole('option', { name: /Asia\/Tokyo/ }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('Time zone set to Tokyo');
    svc.saveTimezone.mockClear();
    done.undo();
    await waitFor(() => expect(svc.saveTimezone).toHaveBeenCalledWith(null));
  });

  it('a failed time zone save shows under the field, not as a toast', async () => {
    svc.saveTimezone.mockRejectedValue(new Error('boom'));
    const { user } = await openPage(true);
    await user.click(screen.getByRole('combobox', { name: 'Time zone' }));
    await user.type(await screen.findByPlaceholderText('Search time zones'), 'Tokyo');
    await user.click(await screen.findByRole('option', { name: /Asia\/Tokyo/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't save the time zone. Try again.");
    expect(toasts.fxDone).not.toHaveBeenCalled();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it('cancelling an email change says so, with no Undo', async () => {
    svc.getPending.mockResolvedValue(PENDING);
    const { user } = await openPage(true);
    expect(
      await screen.findByText(fxPendingWords(PENDING, 'demo@example.com')),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel email change' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    expect(toasts.fxDone.mock.calls[0][0]).toEqual({
      what: 'Email change cancelled',
      forWhom: 'new@example.com',
    });
  });
});

describe('the current password (switch on)', () => {
  it('is not kept, shown, toasted, logged or stored once sent', async () => {
    const logs = (['log', 'info', 'warn', 'error', 'debug'] as const).map((k) =>
      vi.spyOn(console, k),
    );
    const store = vi.spyOn(Storage.prototype, 'setItem');
    const { user } = await openPage(true);
    const dialog = await openChangeEmail(true, user);
    await user.type(within(dialog).getByLabelText('New email'), 'new@example.com');
    const password = within(dialog).getByLabelText('Current password') as HTMLInputElement;
    expect(password).toHaveAttribute('type', 'password');
    expect(password).toHaveAttribute('autocomplete', 'current-password');
    await user.type(password, PASSWORD);
    await user.click(within(dialog).getByRole('button', { name: 'Send approval link' }));
    await screen.findByText(/Approve it from demo@example.com/);

    expect(document.body.innerHTML).not.toContain(PASSWORD);
    expect(JSON.stringify(Object.values(toasts).flatMap((t) => t.mock.calls))).not.toContain(PASSWORD);
    for (const spy of logs) expect(JSON.stringify(spy.mock.calls)).not.toContain(PASSWORD);
    expect(JSON.stringify(store.mock.calls)).not.toContain(PASSWORD);
    expect(document.cookie).not.toContain(PASSWORD);
    logs.forEach((s) => s.mockRestore());
    store.mockRestore();
  });

  it('is cleared from the field when the request is refused', async () => {
    const { InvalidPasswordError } = await import('@/services/email-change-service');
    svc.request.mockRejectedValue(new InvalidPasswordError('Incorrect password.'));
    const { user } = await openPage(true);
    const dialog = await openChangeEmail(true, user);
    await user.type(within(dialog).getByLabelText('New email'), 'new@example.com');
    const password = within(dialog).getByLabelText('Current password') as HTMLInputElement;
    await user.type(password, PASSWORD);
    await user.click(within(dialog).getByRole('button', { name: 'Send approval link' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Incorrect password.');
    expect(password.value).toBe('');
    expect(document.body.innerHTML).not.toContain(PASSWORD);
  });

  it('the dialog hides the page red action while open', async () => {
    const { user } = await openPage(true);
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeInTheDocument();
    await openChangeEmail(true, user);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Edit profile' })).toBeNull());
  });
});

describe('pure words', () => {
  it('names the inbox a change waits on', () => {
    expect(fxPendingWords(PENDING, 'demo@example.com')).toBe(
      'Your email changes to new@example.com once demo@example.com approves it.',
    );
    expect(fxPendingWords({ ...PENDING, status: 'PENDING_NEW' }, 'demo@example.com')).toBe(
      'Your email changes to new@example.com once that inbox confirms it.',
    );
  });
  it('names a zone by its city', () => {
    expect(fxZoneCity('Asia/Kuala_Lumpur')).toBe('Kuala Lumpur');
    expect(fxZoneCity('America/Argentina/Buenos_Aires')).toBe('Buenos Aires');
    expect(fxZoneCity('UTC')).toBe('UTC');
  });
});

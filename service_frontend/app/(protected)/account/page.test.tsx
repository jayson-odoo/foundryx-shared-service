import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { __resetAccountNameOverride } from './components/use-account-form';
import Page from './page';

/** Container/Toolbar read layout settings - provide the real provider. */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

// Hoisted spies so vi.mock factories can reference them.
const { getPending, request, cancel, sessionUpdate, identity, updateProfile, routerPush } =
  vi.hoisted(() => ({
    getPending: vi.fn(),
    request: vi.fn(),
    cancel: vi.fn(),
    sessionUpdate: vi.fn(),
    identity: vi.fn(),
    updateProfile: vi.fn(),
    routerPush: vi.fn(),
  }));

vi.mock('@/services/auth-service', () => ({
  AuthError: class AuthError extends Error {},
  authService: { signin: vi.fn(), identity },
}));

vi.mock('@/services/account-service', () => ({
  accountService: { updateProfile },
}));

vi.mock('@/services/email-change-service', () => {
  class InvalidPasswordError extends Error {}
  class InvalidTokenError extends Error {}
  class EmailTakenError extends Error {}
  class RateLimitError extends Error {
    retryAfterSeconds: number | null = null;
  }
  return {
    InvalidPasswordError,
    InvalidTokenError,
    EmailTakenError,
    RateLimitError,
    emailChangeService: {
      getPending,
      request,
      cancel,
      approve: vi.fn(),
      verify: vi.fn(),
    },
  };
});

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    update: sessionUpdate,
    data: {
      user: {
        id: '1',
        name: 'Demo User',
        email: 'demo@example.com',
        roles: [{ id: 'r1', name: 'Admin' }],
        permissions: [],
      },
    },
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/account',
  useSearchParams: () => new URLSearchParams(),
}));

/** Sign-in concerns live in the form "…" Actions menu (plan 06 iteration). */
async function openChangeEmail(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^actions$/i }));
  await user.click(await screen.findByRole('menuitem', { name: /change email/i }));
}

describe('My Account page', () => {
  beforeEach(() => {
    __resetAccountNameOverride();
    getPending.mockReset().mockResolvedValue(null);
    request.mockReset();
    cancel.mockReset().mockResolvedValue(undefined);
    sessionUpdate.mockReset().mockResolvedValue(null);
    updateProfile.mockReset().mockImplementation(async (input) => input);
    // Full identity surface (plan 06 D8 generalized the drift check) -
    // must MATCH the mocked session or every render fires update().
    identity.mockReset().mockResolvedValue({
      email: 'demo@example.com',
      name: 'Demo User',
      avatar: null,
      roles: [{ id: 'r1', name: 'Admin' }],
      permissions: [],
      isPlatformTenant: false,
    });
  });

  it('refreshes the session ONLY when the backend email diverged', async () => {
    // Matching identity → no update() (a bare update-on-mount loops the
    // protected layout's loading state - review fix).
    const { unmount } = render(<Page />);
    await screen.findAllByText('Demo User');
    await waitFor(() => expect(identity).toHaveBeenCalled());
    expect(sessionUpdate).not.toHaveBeenCalled();
    unmount();

    // Diverged identity (ceremony completed elsewhere) → one update().
    identity.mockResolvedValue({
      email: 'flipped@example.com',
      name: 'Demo User',
      avatar: null,
      roles: [{ id: 'r1', name: 'Admin' }],
      permissions: [],
      isPlatformTenant: false,
    });
    render(<Page />);
    await waitFor(() => expect(sessionUpdate).toHaveBeenCalledTimes(1));
  });

  it('renders the Resource form: title, subtitle, roles, Edit toggle, tabs', async () => {
    render(<Page />);
    // Title (header) + Name row (Profile tab) both carry the name.
    expect(await screen.findAllByText('Demo User')).toHaveLength(2);
    expect(screen.getAllByText('demo@example.com').length).toBeGreaterThan(0);
    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /profile/i })).toBeInTheDocument();
    // Security tab is gone - sign-in concerns live in the "…" menu.
    expect(screen.queryByRole('tab', { name: /security/i })).not.toBeInTheDocument();
  });

  it('offers Change email + Reset password in the Actions menu', async () => {
    const user = userEvent.setup();
    render(<Page />);
    await user.click(await screen.findByRole('button', { name: /^actions$/i }));
    expect(
      await screen.findByRole('menuitem', { name: /change email/i }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', { name: /reset password/i }));
    expect(routerPush).toHaveBeenCalledWith('/reset-password');
  });

  it('copies the email to the clipboard on click', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    // AFTER setup(): userEvent installs its own clipboard stub at setup time
    // and would shadow this one. jsdom's property is getter-only - define.
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    render(<Page />);
    // The Email row value (button), not the header subtitle.
    await user.click(
      await screen.findByRole('button', { name: 'demo@example.com' }),
    );
    expect(writeText).toHaveBeenCalledWith('demo@example.com');
  });

  it('edits the name via the global Edit toggle (plan 06)', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    const input = await screen.findByPlaceholderText('Full name');
    await user.clear(input);
    await user.type(input, 'Renamed Person');
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(updateProfile).toHaveBeenCalledWith({ name: 'Renamed Person' }),
    );
    // Session re-pull requested (name rides the jwt update branch).
    await waitFor(() => expect(sessionUpdate).toHaveBeenCalled());
    // Back in read mode with the new name shown (module override bridges
    // Phase A, where the mock isn't behind /auth/me).
    expect((await screen.findAllByText('Renamed Person')).length).toBeGreaterThan(0);
    expect(screen.queryByPlaceholderText('Full name')).not.toBeInTheDocument();
  });

  it('blocks save on a blank name', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    await user.clear(await screen.findByPlaceholderText('Full name'));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(updateProfile).not.toHaveBeenCalled();
  });

  it('shows the pending banner when a request is outstanding', async () => {
    getPending.mockResolvedValue({
      newEmail: 'next@example.com',
      status: 'PENDING_OLD',
      createdAt: '2026-06-06T00:00:00Z',
      expiresAt: '2026-06-06T01:00:00Z',
    });
    render(<Page />);
    expect(
      await screen.findByText(
        /change to next@example\.com awaits approval from your current inbox/i,
      ),
    ).toBeInTheDocument();
  });

  it('renders the new-side wording once the old side approved', async () => {
    getPending.mockResolvedValue({
      newEmail: 'next@example.com',
      status: 'PENDING_NEW',
      createdAt: '2026-06-06T00:00:00Z',
      expiresAt: '2026-06-06T01:00:00Z',
    });
    render(<Page />);
    expect(
      await screen.findByText(
        /change to next@example\.com awaits confirmation from the new inbox/i,
      ),
    ).toBeInTheDocument();
  });

  it('walks the request flow: form → check-your-inbox → pending banner', async () => {
    request.mockResolvedValue({
      newEmail: 'next@example.com',
      status: 'PENDING_OLD',
      createdAt: '2026-06-06T00:00:00Z',
      expiresAt: '2026-06-06T01:00:00Z',
    });
    const user = userEvent.setup();
    render(<Page />);
    await openChangeEmail(user);
    await user.type(
      screen.getByPlaceholderText('you@example.com'),
      'next@example.com',
    );
    await user.type(
      screen.getByPlaceholderText(/your current password/i),
      'Demo1234!',
    );
    await user.click(screen.getByRole('button', { name: /send approval link/i }));

    expect(await screen.findByText(/check your current inbox/i)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('next@example.com', 'Demo1234!');

    // Close the dialog - the page underneath now shows the pending banner.
    await user.click(screen.getByRole('button', { name: /got it/i }));
    expect(
      await screen.findByText(
        /change to next@example\.com awaits approval from your current inbox/i,
      ),
    ).toBeInTheDocument();
  });

  it('surfaces a wrong-password error inside the dialog', async () => {
    const { InvalidPasswordError } = await import(
      '@/services/email-change-service'
    );
    request.mockRejectedValue(new InvalidPasswordError('Incorrect password.'));
    const user = userEvent.setup();
    render(<Page />);
    await openChangeEmail(user);
    await user.type(
      screen.getByPlaceholderText('you@example.com'),
      'next@example.com',
    );
    await user.type(
      screen.getByPlaceholderText(/your current password/i),
      'nope',
    );
    await user.click(screen.getByRole('button', { name: /send approval link/i }));

    expect(await screen.findByText('Incorrect password.')).toBeInTheDocument();
    // Still on the form - no "check your inbox" state, no banner.
    expect(screen.queryByText(/check your current inbox/i)).not.toBeInTheDocument();
  });

  it('validates the form before calling the service', async () => {
    const user = userEvent.setup();
    render(<Page />);
    await openChangeEmail(user);
    await user.type(screen.getByPlaceholderText('you@example.com'), 'not-an-email');
    await user.click(screen.getByRole('button', { name: /send approval link/i }));

    expect(
      await screen.findByText(/please enter a valid email address/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/current password is required/i),
    ).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('cancels the outstanding request from the banner', async () => {
    getPending.mockResolvedValue({
      newEmail: 'next@example.com',
      status: 'PENDING_OLD',
      createdAt: '2026-06-06T00:00:00Z',
      expiresAt: '2026-06-06T01:00:00Z',
    });
    const user = userEvent.setup();
    render(<Page />);

    await user.click(
      await screen.findByRole('button', { name: /cancel request/i }),
    );
    await waitFor(() => expect(cancel).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByText(/awaits approval from your current inbox/i),
      ).not.toBeInTheDocument(),
    );
  });
});

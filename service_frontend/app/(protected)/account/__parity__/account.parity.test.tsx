/**
 * Switch-off parity for My Account (Foundryx UIUX slice W4-ACCOUNT): the page
 * at rest, editing the name, with an email change waiting, and the change
 * email dialog (form and "check your inbox"), rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one
 * of these snapshots updated is wrong by definition (fix the code, never the
 * snapshot).
 */
import type { ReactElement } from 'react';
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { __resetAccountNameOverride } from '../components/use-account-form';
import Page from '../page';

const { getPending, request, identity } = vi.hoisted(() => ({
  getPending: vi.fn(),
  request: vi.fn(),
  identity: vi.fn(),
}));

vi.mock('@/lib/datetime', async (orig) => ({
  ...((await orig()) as object),
  browserTimeZone: () => 'Asia/Kuala_Lumpur',
}));
vi.mock('@/services/auth-service', () => ({
  AuthError: class AuthError extends Error {},
  authService: { signin: vi.fn(), identity },
}));
vi.mock('@/services/account-service', () => ({
  accountService: { updateProfile: vi.fn(async (input: unknown) => input) },
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
    emailChangeService: { getPending, request, cancel: vi.fn(), approve: vi.fn(), verify: vi.fn() },
  };
});
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    update: vi.fn(async () => null),
    data: {
      user: {
        id: '1',
        name: 'Demo User',
        email: 'demo@example.com',
        roles: [{ id: 'r1', name: 'Admin' }],
        permissions: [],
        timezone: null,
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/account',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

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

function render(ui: ReactElement) {
  return rtlRender(
    <SettingsProvider>
      <TooltipsProvider>{ui}</TooltipsProvider>
    </SettingsProvider>,
  );
}

async function openPage() {
  const view = render(<Page />);
  await screen.findAllByText('Demo User');
  await waitFor(() => expect(getPending).toHaveBeenCalled());
  await waitFor(() => expect(identity).toHaveBeenCalled());
  return view;
}

beforeEach(() => {
  __resetAccountNameOverride();
  getPending.mockReset().mockResolvedValue(null);
  request.mockReset();
  identity.mockReset().mockResolvedValue({
    email: 'demo@example.com',
    name: 'Demo User',
    avatar: null,
    roles: [{ id: 'r1', name: 'Admin' }],
    permissions: [],
    isPlatformTenant: false,
    timezone: null,
  });
});

describe('parity (switch off): My Account', () => {
  it('at rest, then editing the name', async () => {
    const user = userEvent.setup();
    const { container } = await openPage();
    expect(stable(container)).toMatchSnapshot();
    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    const name = await screen.findByPlaceholderText('Full name');
    await user.clear(name);
    await user.type(name, 'Nurul Huda');
    expect(stable(container)).toMatchSnapshot();
  });

  it('with an email change waiting for the current inbox', async () => {
    getPending.mockResolvedValue({
      newEmail: 'new@example.com',
      status: 'PENDING_OLD',
      expiresAt: '2026-11-20T00:00:00Z',
    });
    const { container } = await openPage();
    await screen.findByText(/awaits approval/);
    expect(stable(container)).toMatchSnapshot();
  });

  it('the change email dialog, then its "check your inbox" state', async () => {
    const user = userEvent.setup();
    request.mockResolvedValue({
      newEmail: 'new@example.com',
      status: 'PENDING_OLD',
      expiresAt: '2026-11-20T00:00:00Z',
    });
    await openPage();
    await user.click(await screen.findByRole('button', { name: /^actions$/i }));
    await user.click(await screen.findByRole('menuitem', { name: /change email/i }));
    const dialog = await screen.findByRole('dialog');
    expect(stable(dialog)).toMatchSnapshot();
    await user.type(screen.getByLabelText('New email'), 'new@example.com');
    await user.type(screen.getByLabelText('Current password'), 'pw-123');
    await user.click(screen.getByRole('button', { name: 'Send approval link' }));
    await screen.findByText('Check your current inbox');
    expect(stable(screen.getByRole('dialog'))).toMatchSnapshot();
  });
});

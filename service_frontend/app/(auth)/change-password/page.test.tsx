import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './page';

// Hoisted spies so the vi.mock factories below can reference them.
const { setPassword, push, getToken } = vi.hoisted(() => ({
  setPassword: vi.fn(),
  push: vi.fn(),
  getToken: vi.fn<() => string | null>(() => 'valid-token'),
}));

vi.mock('@/services/password-service', () => {
  class InvalidTokenError extends Error {}
  class RateLimitError extends Error {
    retryAfterSeconds: number | null;
    constructor(message: string, retryAfterSeconds: number | null = null) {
      super(message);
      this.retryAfterSeconds = retryAfterSeconds;
    }
  }
  return {
    InvalidTokenError,
    RateLimitError,
    passwordService: { requestReset: vi.fn(), setPassword },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/change-password',
  useSearchParams: () => ({ get: (key: string) => (key === 'token' ? getToken() : null) }),
}));

const STRONG_PASSWORD = 'NewPass1!';

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  password = STRONG_PASSWORD,
  confirm = password,
) {
  await user.type(screen.getByPlaceholderText('Your new password'), password);
  await user.type(
    screen.getByPlaceholderText('Confirm your new password'),
    confirm,
  );
  await user.click(screen.getByRole('button', { name: /reset password/i }));
}

describe('Change-password (redeem) page', () => {
  beforeEach(() => {
    setPassword.mockReset();
    push.mockReset();
    getToken.mockReset();
    getToken.mockReturnValue('valid-token');
  });

  it('renders the form with policy hint when a token is present', () => {
    render(<Page />);
    expect(
      screen.getByRole('heading', { name: /set a new password/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Your new password'),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Confirm your new password'),
    ).toBeInTheDocument();
  });

  it('shows the expired-link state when no token is in the URL', () => {
    getToken.mockReturnValue(null);
    render(<Page />);
    expect(
      screen.getByRole('heading', { name: /link expired/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /request a new link/i }),
    ).toHaveAttribute('href', '/reset-password');
    expect(setPassword).not.toHaveBeenCalled();
  });

  it('enforces the password policy client-side', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await fillAndSubmit(user, 'weakpass');

    expect(
      await screen.findByText(/must contain at least one uppercase letter/i),
    ).toBeInTheDocument();
    expect(setPassword).not.toHaveBeenCalled();
  });

  it('blocks mismatched confirmation', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await fillAndSubmit(user, STRONG_PASSWORD, 'Different1!');

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(setPassword).not.toHaveBeenCalled();
  });

  it('redeems the token and shows success + redirect to signin', async () => {
    setPassword.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<Page />);

    await fillAndSubmit(user);

    expect(
      await screen.findByRole('heading', { name: /password updated/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to sign in/i })).toHaveAttribute(
      'href',
      '/signin',
    );
    expect(setPassword).toHaveBeenCalledWith('valid-token', STRONG_PASSWORD);
    await waitFor(() => expect(push).toHaveBeenCalledWith('/signin'), {
      timeout: 4000,
    });
  });

  it('shows the expired-link state when the token is rejected', async () => {
    const { InvalidTokenError } = await import('@/services/password-service');
    setPassword.mockRejectedValueOnce(new InvalidTokenError('bad token'));
    const user = userEvent.setup();
    render(<Page />);

    await fillAndSubmit(user);

    expect(
      await screen.findByRole('heading', { name: /link expired/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /request a new link/i }),
    ).toHaveAttribute('href', '/reset-password');
  });

  it('maps a 429 to the friendly throttle message and keeps the form', async () => {
    const { RateLimitError } = await import('@/services/password-service');
    setPassword.mockRejectedValueOnce(new RateLimitError('Too many attempts.', 120));
    const user = userEvent.setup();
    render(<Page />);

    await fillAndSubmit(user);

    expect(
      await screen.findByText(/too many attempts - please try again in ~2 minutes/i),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Your new password'),
    ).toBeInTheDocument();
  });

  it('toggles visibility on both password fields', async () => {
    const user = userEvent.setup();
    render(<Page />);

    const password = screen.getByPlaceholderText('Your new password');
    const confirm = screen.getByPlaceholderText('Confirm your new password');
    expect(password).toHaveAttribute('type', 'password');
    expect(confirm).toHaveAttribute('type', 'password');

    await user.click(screen.getByRole('button', { name: /^show password$/i }));
    expect(password).toHaveAttribute('type', 'text');

    await user.click(
      screen.getByRole('button', { name: /show password confirmation/i }),
    );
    expect(confirm).toHaveAttribute('type', 'text');
  });
});

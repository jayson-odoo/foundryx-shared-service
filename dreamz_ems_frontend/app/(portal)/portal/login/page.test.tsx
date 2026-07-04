import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './page';

// Hoisted spies so the vi.mock factories can reference them.
const { signin, requestOtp, signinOtp, push } = vi.hoisted(() => ({
  signin: vi.fn(),
  requestOtp: vi.fn(),
  signinOtp: vi.fn(),
  push: vi.fn(),
}));

// Drive the real hook against a mocked service (UI → hook → service).
vi.mock('@/services/portal-auth-service', () => {
  class PortalAuthError extends Error {}
  class RateLimitError extends Error {
    retryAfterSeconds: number | null;
    constructor(message: string, retryAfterSeconds: number | null = null) {
      super(message);
      this.retryAfterSeconds = retryAfterSeconds;
    }
  }
  return {
    PortalAuthError,
    RateLimitError,
    InvalidTokenError: class extends Error {},
    portalAuthService: { signin, requestOtp, signinOtp },
  };
});

vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({
    branding: { isBranded: false, tenantName: null, appName: null },
    isResolved: true,
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/portal/login',
  useSearchParams: () => new URLSearchParams(),
}));

describe('Portal login page', () => {
  beforeEach(() => {
    signin.mockReset();
    requestOtp.mockReset();
    signinOtp.mockReset();
    push.mockReset();
  });

  it('renders password mode by default with email + password + submit', () => {
    render(<Page />);
    expect(
      screen.getByRole('heading', { name: /welcome/i }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/your email/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/your password/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /^sign in$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /sign in with email code/i }),
    ).toBeInTheDocument();
  });

  it('password login redirects to the dashboard on success', async () => {
    signin.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<Page />);

    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'profile@example.com',
    );
    await user.type(screen.getByPlaceholderText(/your password/i), 'secret123');
    await user.click(screen.getByRole('button', { name: /^sign in$/i }));

    await waitFor(() =>
      expect(signin).toHaveBeenCalledWith(
        expect.objectContaining({ email: 'profile@example.com' }),
      ),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith('/portal/dashboard'),
    );
  });

  it('shows the credentials error and stays put on a rejected login', async () => {
    const { PortalAuthError } = await import('@/services/portal-auth-service');
    signin.mockRejectedValueOnce(
      new PortalAuthError('Invalid email or password.'),
    );
    const user = userEvent.setup();
    render(<Page />);

    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'profile@example.com',
    );
    await user.type(screen.getByPlaceholderText(/your password/i), 'nope1234');
    await user.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(
      await screen.findByText('Invalid email or password.'),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('OTP mode: request a code, then verify and sign in', async () => {
    requestOtp.mockResolvedValueOnce({ message: 'Code sent if the account exists.' });
    signinOtp.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<Page />);

    // Switch to OTP mode.
    await user.click(
      screen.getByRole('button', { name: /sign in with email code/i }),
    );
    expect(
      screen.getByRole('button', { name: /send code/i }),
    ).toBeInTheDocument();

    // Step 1: request the code.
    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'profile@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send code/i }));

    await waitFor(() =>
      expect(requestOtp).toHaveBeenCalledWith('profile@example.com'),
    );

    // The uniform enumeration-safe confirmation appears + the code step.
    expect(
      await screen.findByText(/code sent if the account exists/i),
    ).toBeInTheDocument();

    // Step 2: enter the 6-digit code + verify.
    await user.type(screen.getByPlaceholderText(/6-digit code/i), '123456');
    await user.click(
      screen.getByRole('button', { name: /verify & sign in/i }),
    );

    await waitFor(() =>
      expect(signinOtp).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'profile@example.com',
          code: '123456',
        }),
      ),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith('/portal/dashboard'),
    );
  });

  it('OTP request shows the uniform message even for an unknown email', async () => {
    requestOtp.mockResolvedValueOnce({
      message: 'If an account exists for this email, a verification code has been sent.',
    });
    const user = userEvent.setup();
    render(<Page />);

    await user.click(
      screen.getByRole('button', { name: /sign in with email code/i }),
    );
    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'nobody@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send code/i }));

    expect(
      await screen.findByText(/if an account exists for this email/i),
    ).toBeInTheDocument();
  });

  it('validates the 6-digit code format before submitting', async () => {
    requestOtp.mockResolvedValueOnce({ message: 'Code sent.' });
    const user = userEvent.setup();
    render(<Page />);

    await user.click(
      screen.getByRole('button', { name: /sign in with email code/i }),
    );
    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'profile@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send code/i }));

    await user.type(screen.getByPlaceholderText(/6-digit code/i), '12');
    await user.click(
      screen.getByRole('button', { name: /verify & sign in/i }),
    );

    expect(await screen.findByText(/enter the 6-digit code/i)).toBeInTheDocument();
    expect(signinOtp).not.toHaveBeenCalled();
  });

  it('links to the portal forgot-password page', () => {
    render(<Page />);
    expect(
      screen.getByRole('link', { name: /forgot password/i }),
    ).toHaveAttribute('href', '/portal/reset-password');
  });
});

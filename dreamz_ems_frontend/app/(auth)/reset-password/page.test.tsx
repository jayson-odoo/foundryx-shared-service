import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './page';

// Hoisted spy so the vi.mock factory below can reference it.
const { requestReset } = vi.hoisted(() => ({ requestReset: vi.fn() }));

// Control the password service directly so the page+hook wiring is tested
// deterministically (no mock delay).
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
    passwordService: { requestReset, setPassword: vi.fn() },
  };
});

const RESET_MESSAGE =
  'If an account exists for this email, a reset link has been sent.';

describe('Reset-password (request) page', () => {
  beforeEach(() => {
    requestReset.mockReset();
  });

  it('renders the heading, email field, submit and back link', () => {
    render(<Page />);
    expect(
      screen.getByRole('heading', { name: /forgot your password/i }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/your email/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /send reset link/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /back to sign in/i }),
    ).toHaveAttribute('href', '/signin');
  });

  it('blocks submit on an invalid email', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await user.type(screen.getByPlaceholderText(/your email/i), 'not-an-email');
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(
      await screen.findByText(/please enter a valid email address/i),
    ).toBeInTheDocument();
    expect(requestReset).not.toHaveBeenCalled();
  });

  it('shows the uniform confirmation on success (enumeration-safe)', async () => {
    requestReset.mockResolvedValueOnce({ message: RESET_MESSAGE });
    const user = userEvent.setup();
    render(<Page />);

    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'demo@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(await screen.findByText(RESET_MESSAGE)).toBeInTheDocument();
    // The form is gone — no retry surface that could leak existence.
    expect(screen.queryByPlaceholderText(/your email/i)).not.toBeInTheDocument();
    expect(requestReset).toHaveBeenCalledWith('demo@example.com');
  });

  it('maps a 429 to the friendly throttle message', async () => {
    const { RateLimitError } = await import('@/services/password-service');
    requestReset.mockRejectedValueOnce(new RateLimitError('Too many attempts.', 900));
    const user = userEvent.setup();
    render(<Page />);

    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'throttled@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(
      await screen.findByText(/too many attempts — please try again in ~15 minutes/i),
    ).toBeInTheDocument();
    // Form stays so the user can retry after the window.
    expect(screen.getByPlaceholderText(/your email/i)).toBeInTheDocument();
  });

  it('shows a generic error on an unexpected failure', async () => {
    requestReset.mockRejectedValueOnce(new Error('boom'));
    const user = userEvent.setup();
    render(<Page />);

    await user.type(
      screen.getByPlaceholderText(/your email/i),
      'demo@example.com',
    );
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(
      await screen.findByText(/something went wrong/i),
    ).toBeInTheDocument();
  });
});

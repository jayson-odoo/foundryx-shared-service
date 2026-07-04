import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './page';

// Hoisted spies so the vi.mock factories below can reference them.
const { signin, push } = vi.hoisted(() => ({ signin: vi.fn(), push: vi.fn() }));

// Control the auth service directly so the page+hook wiring is tested
// deterministically (no 800ms mock delay, no next-auth import).
vi.mock('@/services/auth-service', () => {
  class AuthError extends Error {}
  return { AuthError, authService: { signin } };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/signin',
  useSearchParams: () => new URLSearchParams(),
}));

describe('Signin page', () => {
  beforeEach(() => {
    signin.mockReset();
    push.mockReset();
  });

  it('renders the welcome heading and submit', () => {
    render(<Page />);
    expect(
      screen.getByRole('heading', { name: /welcome back/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('hides "Create an Account" while signup is disabled (plan 10 D3)', () => {
    render(<Page />);
    expect(
      screen.queryByRole('link', { name: /create an account/i }),
    ).not.toBeInTheDocument();
  });

  it('renders the Remember me checkbox unchecked by default', () => {
    render(<Page />);
    const checkbox = screen.getByRole('checkbox', { name: /remember me/i });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).toHaveAttribute('data-state', 'unchecked');
  });

  it('passes rememberMe through to the auth service when checked', async () => {
    signin.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<Page />);

    await user.type(screen.getByPlaceholderText(/your email/i), 'demo@example.com');
    await user.type(screen.getByPlaceholderText(/your password/i), 'demo1234');
    await user.click(screen.getByRole('checkbox', { name: /remember me/i }));
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() =>
      expect(signin).toHaveBeenCalledWith(
        expect.objectContaining({ rememberMe: true }),
      ),
    );
  });

  it('blocks submit and shows validation messages when fields are empty', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(
      await screen.findByText(/please enter a valid email address/i),
    ).toBeInTheDocument();
    expect(signin).not.toHaveBeenCalled();
  });

  it('rejects a malformed email', async () => {
    const user = userEvent.setup();
    render(<Page />);

    await user.type(screen.getByPlaceholderText(/your email/i), 'not-an-email');
    await user.type(screen.getByPlaceholderText(/your password/i), 'secret123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(
      await screen.findByText(/please enter a valid email address/i),
    ).toBeInTheDocument();
    expect(signin).not.toHaveBeenCalled();
  });

  it('shows a generic error and stays put when credentials are rejected', async () => {
    const { AuthError } = await import('@/services/auth-service');
    signin.mockRejectedValueOnce(new AuthError('Invalid email or password.'));
    const user = userEvent.setup();
    render(<Page />);

    await user.type(screen.getByPlaceholderText(/your email/i), 'wrong@example.com');
    await user.type(screen.getByPlaceholderText(/your password/i), 'badpass1');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(
      await screen.findByText('Invalid email or password.'),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('redirects home on a successful sign-in', async () => {
    signin.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<Page />);

    await user.type(screen.getByPlaceholderText(/your email/i), 'demo@example.com');
    await user.type(screen.getByPlaceholderText(/your password/i), 'demo1234');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
  });

  it('toggles password visibility', async () => {
    const user = userEvent.setup();
    render(<Page />);
    const password = screen.getByPlaceholderText(/your password/i);
    expect(password).toHaveAttribute('type', 'password');

    await user.click(screen.getByRole('button', { name: /show password/i }));
    expect(password).toHaveAttribute('type', 'text');
  });
});

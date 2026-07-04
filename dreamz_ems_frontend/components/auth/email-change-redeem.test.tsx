import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ApprovePage from '@/app/(auth)/approve-email-change/page';
import VerifyPage from '@/app/(auth)/verify-email-change/page';

const { approve, verify, searchParams } = vi.hoisted(() => ({
  approve: vi.fn(),
  verify: vi.fn(),
  searchParams: { value: new URLSearchParams() },
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
      getPending: vi.fn(),
      request: vi.fn(),
      cancel: vi.fn(),
      approve,
      verify,
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/approve-email-change',
  useSearchParams: () => searchParams.value,
}));

describe('Email-change redeem pages', () => {
  beforeEach(() => {
    approve.mockReset();
    verify.mockReset();
    searchParams.value = new URLSearchParams('token=tok-123');
  });

  it('approve: redeems only on the explicit click, then shows the next step', async () => {
    approve.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ApprovePage />);

    expect(
      screen.getByRole('heading', { name: /approve email change/i }),
    ).toBeInTheDocument();
    // Never on mount — single-use tokens must survive mail-scanner prefetches.
    expect(approve).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /approve change/i }));
    expect(approve).toHaveBeenCalledWith('tok-123');
    expect(await screen.findByText(/change approved/i)).toBeInTheDocument();
    expect(screen.getByText(/open the inbox of your new address/i)).toBeInTheDocument();
  });

  it('verify: completes the ceremony and routes to sign-in', async () => {
    verify.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<VerifyPage />);

    await user.click(screen.getByRole('button', { name: /confirm new email/i }));
    expect(verify).toHaveBeenCalledWith('tok-123');
    expect(await screen.findByText(/email updated/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to sign in/i })).toHaveAttribute(
      'href',
      '/signin',
    );
  });

  it('shows the dead-link state when the token is missing', () => {
    searchParams.value = new URLSearchParams();
    render(<ApprovePage />);
    expect(screen.getByRole('heading', { name: /link expired/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to my account/i })).toHaveAttribute(
      'href',
      '/account',
    );
  });

  it('flips to the dead-link state when the token is rejected', async () => {
    const { InvalidTokenError } = await import('@/services/email-change-service');
    approve.mockRejectedValue(new InvalidTokenError('bad token'));
    const user = userEvent.setup();
    render(<ApprovePage />);

    await user.click(screen.getByRole('button', { name: /approve change/i }));
    expect(
      await screen.findByRole('heading', { name: /link expired/i }),
    ).toBeInTheDocument();
  });

  it('verify: surfaces the uniqueness race without killing the page', async () => {
    const { EmailTakenError } = await import('@/services/email-change-service');
    verify.mockRejectedValue(
      new EmailTakenError('This email address is no longer available.'),
    );
    const user = userEvent.setup();
    render(<VerifyPage />);

    await user.click(screen.getByRole('button', { name: /confirm new email/i }));
    expect(
      await screen.findByText('This email address is no longer available.'),
    ).toBeInTheDocument();
    // Not a dead link — the button stays for a retry after a fresh request.
    expect(
      screen.getByRole('button', { name: /confirm new email/i }),
    ).toBeInTheDocument();
  });
});

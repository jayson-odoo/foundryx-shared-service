import { useState } from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { OtpCodeField, useResendCooldown } from './otp-code-field';

/** Mirrors the CRM portal code field (lane FEEDBACK-SHARE-SS-HOST). */
function Harness({ onComplete, pending = false }: { onComplete: (c: string) => void; pending?: boolean }) {
  const [code, setCode] = useState('');
  const cooldown = useResendCooldown();
  return (
    <OtpCodeField
      id="c"
      value={code}
      onChange={setCode}
      onComplete={onComplete}
      cooldown={cooldown.seconds}
      sent
      pending={pending}
      onResend={() => cooldown.start(3)}
    />
  );
}

afterEach(() => vi.useRealTimers());

describe('OtpCodeField', () => {
  it('one numeric field, completes once on the 6th digit', async () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    const field = screen.getByLabelText('Verification code');
    expect(field).toHaveAttribute('placeholder', '6-digit code');
    expect(field).toHaveAttribute('inputmode', 'numeric');
    expect(field).toHaveAttribute('maxlength', '6');
    await userEvent.type(field, '12a345');
    expect(onComplete).not.toHaveBeenCalled();
    await userEvent.type(field, '6');
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith('123456');
  });

  it('does not complete while pending', async () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} pending />);
    await userEvent.type(screen.getByLabelText('Verification code'), '123456');
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('resend counts down, then reads Resend code', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Harness onComplete={vi.fn()} />);
    const btn = screen.getByRole('button', { name: 'Resend code' });
    await userEvent.click(btn);
    expect(screen.getByRole('button', { name: 'Resend in 3s' })).toBeDisabled();
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(screen.getByRole('button', { name: 'Resend code' })).toBeEnabled();
  });

  it('a status replaces the resend button', () => {
    render(
      <OtpCodeField value="" onChange={vi.fn()} onComplete={vi.fn()} cooldown={0} sent pending={false}
        onResend={vi.fn()} status={<span>Signing you in as +60 12 345 0002</span>} />,
    );
    expect(screen.getByText('Signing you in as +60 12 345 0002')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Resend/ })).toBeNull();
  });
});

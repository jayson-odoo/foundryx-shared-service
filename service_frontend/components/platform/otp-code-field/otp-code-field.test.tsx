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

  it('checks a given 6-digit value only once, whatever re-renders', () => {
    const first = vi.fn();
    const props = { value: '123456', onChange: vi.fn(), cooldown: 0, sent: true, onResend: vi.fn() };
    const { rerender } = render(<OtpCodeField {...props} onComplete={first} pending={false} />);
    expect(first).toHaveBeenCalledTimes(1);
    const next = vi.fn();
    rerender(<OtpCodeField {...props} onComplete={next} pending={false} />);
    rerender(<OtpCodeField {...props} onComplete={next} pending />);
    rerender(<OtpCodeField {...props} onComplete={next} pending={false} />);
    expect(next).not.toHaveBeenCalled();
    rerender(<OtpCodeField {...props} value="12345" onComplete={next} pending={false} />);
    rerender(<OtpCodeField {...props} value="123457" onComplete={next} pending={false} />);
    expect(next).toHaveBeenCalledWith('123457');
  });

  it('hands focus back to the field when a check ends', () => {
    const props = { value: '', onChange: vi.fn(), onComplete: vi.fn(), cooldown: 0, sent: true, onResend: vi.fn() };
    const { rerender } = render(<OtpCodeField {...props} pending />);
    (document.activeElement as HTMLElement | null)?.blur();
    expect(screen.getByLabelText('Verification code')).not.toHaveFocus();
    rerender(<OtpCodeField {...props} pending={false} />);
    expect(screen.getByLabelText('Verification code')).toHaveFocus();
  });

  it('announces the status row', () => {
    render(
      <OtpCodeField value="" onChange={vi.fn()} onComplete={vi.fn()} cooldown={0} sent pending
        onResend={vi.fn()} status={<span>Signing you in as +60 12 345 0002</span>} />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Signing you in as +60 12 345 0002');
  });
});

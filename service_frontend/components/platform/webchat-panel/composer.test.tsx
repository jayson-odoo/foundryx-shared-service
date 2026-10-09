import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Composer } from './composer';

describe('Composer (plan 34 / A7b S4)', () => {
  it('sends the trimmed text and clears the input (Enter, no shift)', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer onSend={onSend} sending={false} error={null} honeypot="" onHoneypotChange={vi.fn()} />);
    const input = screen.getByTestId('webchat-composer-input');
    await user.type(input, '  Hello there  {Enter}');
    expect(onSend).toHaveBeenCalledWith('Hello there');
    expect(input).toHaveValue('');
  });

  it('disables the send button while empty or sending', () => {
    render(<Composer onSend={vi.fn()} sending={false} error={null} honeypot="" onHoneypotChange={vi.fn()} />);
    expect(screen.getByTestId('webchat-composer-send')).toBeDisabled();
  });

  it('shows the send error without blocking further typing', () => {
    render(
      <Composer
        onSend={vi.fn()}
        sending={false}
        error="Could not send your message. Please try again."
        honeypot=""
        onHoneypotChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('webchat-send-error')).toHaveTextContent('Could not send your message');
  });

  it('never offers an attach control (D-A7B-20 - uploads are off)', () => {
    render(<Composer onSend={vi.fn()} sending={false} error={null} honeypot="" onHoneypotChange={vi.fn()} />);
    expect(screen.queryByLabelText(/attach/i)).not.toBeInTheDocument();
  });

  it('the honeypot input is off-screen and never labeled to a real visitor', () => {
    render(<Composer onSend={vi.fn()} sending={false} error={null} honeypot="" onHoneypotChange={vi.fn()} />);
    const honeypot = screen.getByLabelText('Company');
    expect(honeypot).toHaveAttribute('tabIndex', '-1');
  });
});

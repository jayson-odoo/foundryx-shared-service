import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PreChatStep } from './prechat-step';

const allOff = { askName: false, askEmail: false, askPhone: false };

describe('PreChatStep (plan 34 / A7b S4, D-A7B-23/AC-WEB-53)', () => {
  it('renders ONLY the toggled-on fields', () => {
    render(
      <PreChatStep
        toggles={{ askName: true, askEmail: true, askPhone: false }}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId('webchat-prechat-name')).toBeInTheDocument();
    expect(screen.getByTestId('webchat-prechat-email')).toBeInTheDocument();
    expect(screen.queryByTestId('webchat-prechat-phone')).not.toBeInTheDocument();
  });

  it('renders no fields at all when every toggle is off, only the greeting + composer', () => {
    render(
      <PreChatStep
        toggles={allOff}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('webchat-prechat-name')).not.toBeInTheDocument();
    expect(screen.getByText('Hi there!')).toBeInTheDocument();
    expect(screen.getByTestId('webchat-prechat-send')).toBeInTheDocument();
  });

  it('every field is OPTIONAL - a visitor can send with none of them filled', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PreChatStep
        toggles={{ askName: true, askEmail: true, askPhone: true }}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    await user.type(screen.getByTestId('webchat-prechat-message'), 'Hello');
    await user.click(screen.getByTestId('webchat-prechat-send'));
    expect(onSubmit).toHaveBeenCalledWith('Hello', {});
  });

  it('collects only the filled, toggled-on values alongside the message', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PreChatStep
        toggles={{ askName: true, askEmail: true, askPhone: false }}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    await user.type(screen.getByTestId('webchat-prechat-name'), 'Ada');
    await user.type(screen.getByTestId('webchat-prechat-message'), 'Hi');
    await user.click(screen.getByTestId('webchat-prechat-send'));
    expect(onSubmit).toHaveBeenCalledWith('Hi', { name: 'Ada' });
  });

  it('never sends an empty message (send stays disabled)', () => {
    render(
      <PreChatStep
        toggles={allOff}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId('webchat-prechat-send')).toBeDisabled();
  });
  // Lane FEEDBACK-COMMENT-PHONE-LIKE-PORTAL: the phone field is the ONE shared
  // SS phone input (the CRM portal sign-in field). Every number is made up.
  const phoneOn = { askName: false, askEmail: false, askPhone: true };

  it('the phone field is the shared phone input: Malaysia flag, +60, CRM placeholder', () => {
    render(
      <PreChatStep
        toggles={phoneOn}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Country: Malaysia (+60)' })).toBeInTheDocument();
    expect(screen.getByText('+60')).toBeInTheDocument();
    expect(screen.getByLabelText('Phone')).toHaveAttribute('placeholder', '12-345 6789');
  });

  it('sends the phone as E.164 (trunk 0 dropped)', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PreChatStep
        toggles={phoneOn}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    await user.type(screen.getByLabelText('Phone'), '012-345 0002');
    await user.type(screen.getByTestId('webchat-prechat-message'), 'Hi');
    await user.click(screen.getByTestId('webchat-prechat-send'));
    expect(onSubmit).toHaveBeenCalledWith('Hi', { phone: '+60123450002' });
  });

  it('an incomplete phone is not sent: the field shows its message and the message stays', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PreChatStep
        toggles={phoneOn}
        greeting="Hi there!"
        sending={false}
        error={null}
        honeypot=""
        onHoneypotChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    await user.type(screen.getByLabelText('Phone'), '0123');
    await user.type(screen.getByTestId('webchat-prechat-message'), 'Hi');
    await user.click(screen.getByTestId('webchat-prechat-send'));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a complete phone number.');
    expect(screen.getByTestId('webchat-prechat-message')).toHaveValue('Hi');
  });
});

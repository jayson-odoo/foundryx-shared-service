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
});

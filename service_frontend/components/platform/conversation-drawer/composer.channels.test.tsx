/**
 * Composer capability gating (plan 32 / A7a, AC-CHN-06/07/08/61) - the three
 * window states on a Messenger/Instagram thread, and per-type affordance
 * gating driven by `lib/channel-capabilities.ts`. WhatsApp behaviour (the
 * default `capabilities` prop) is covered unchanged by `conversation-drawer.
 * test.tsx`'s existing CSW suite.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import { Composer } from './composer';

const base = {
  templates: [],
  quickReplies: [],
  isSending: false,
  sendError: null,
  onSend: vi.fn(async () => true),
  onSendTemplate: vi.fn(async () => true),
  onSendMedia: vi.fn(async () => true),
  onSendInteractive: vi.fn(async () => true),
  onSendLocation: vi.fn(async () => true),
  onSendContacts: vi.fn(async () => true),
};

describe('Composer - Messenger/Instagram window states (D-A7-6)', () => {
  it('standard window open: full capabilities, no window marker', () => {
    render(<Composer {...base} windowOpen capabilities={CHANNEL_CAPABILITIES.FACEBOOK} />);
    expect(screen.getByTestId('message-input')).toBeEnabled();
    expect(screen.queryByTestId('csw-banner')).not.toBeInTheDocument();
  });

  it('standard window closed but human-agent window open: composer stays enabled with a neutral marker', () => {
    render(
      <Composer
        {...base}
        windowOpen={false}
        humanAgentWindowOpen
        capabilities={CHANNEL_CAPABILITIES.FACEBOOK}
      />,
    );
    expect(screen.getByTestId('message-input')).toBeEnabled();
    expect(screen.getByTestId('csw-banner')).toBeInTheDocument();
    // No WhatsApp wording, no template affordance (Messenger has no templates).
    expect(screen.queryByText(/24-hour/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('csw-pick-template')).not.toBeInTheDocument();
  });

  it('both windows closed: composer locked with the SAME neutral marker, no template affordance', () => {
    render(
      <Composer
        {...base}
        windowOpen={false}
        humanAgentWindowOpen={false}
        capabilities={CHANNEL_CAPABILITIES.FACEBOOK}
      />,
    );
    expect(screen.getByTestId('message-input')).toBeDisabled();
    expect(screen.getByTestId('csw-banner')).toBeInTheDocument();
    expect(screen.queryByText(/24-hour/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('csw-pick-template')).not.toBeInTheDocument();
  });

  it('WhatsApp default keeps the exact 24-hour + template copy when locked', () => {
    render(<Composer {...base} windowOpen={false} />);
    expect(screen.getByText(/24-hour window has closed/)).toBeInTheDocument();
    expect(screen.getByTestId('csw-pick-template')).toBeInTheDocument();
  });
});

describe('Composer - per-type attach + structured gating', () => {
  it('Messenger offers document attachments and quick replies (Interactive) but no location/contacts', async () => {
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen capabilities={CHANNEL_CAPABILITIES.FACEBOOK} />);
    await user.click(screen.getByTestId('attach-menu'));
    expect(screen.getByTestId('attach-document')).toBeInTheDocument();
    expect(screen.getByTestId('attach-interactive')).toBeInTheDocument();
    expect(screen.queryByTestId('attach-location')).not.toBeInTheDocument();
    expect(screen.queryByTestId('attach-contact')).not.toBeInTheDocument();
    expect(screen.queryByTestId('attach-sticker')).not.toBeInTheDocument();
  });

  it('Instagram offers no file/document attachments (capability table §5.5)', async () => {
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen capabilities={CHANNEL_CAPABILITIES.INSTAGRAM} />);
    await user.click(screen.getByTestId('attach-menu'));
    expect(screen.queryByTestId('attach-document')).not.toBeInTheDocument();
    expect(screen.getByTestId('attach-image')).toBeInTheDocument();
  });

  it('WhatsApp (default) still offers every attachment kind and no regression', async () => {
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen />);
    await user.click(screen.getByTestId('attach-menu'));
    expect(screen.getByTestId('attach-document')).toBeInTheDocument();
    expect(screen.getByTestId('attach-sticker')).toBeInTheDocument();
    expect(screen.getByTestId('attach-location')).toBeInTheDocument();
    expect(screen.getByTestId('attach-contact')).toBeInTheDocument();
  });
});

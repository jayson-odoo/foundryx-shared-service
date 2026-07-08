/**
 * Plan 12 Slice 2 (frontend): interactive/location/contacts builders send the
 * right typed input (AC-12-13/15/16), and the bubble renders each structured
 * body incl. the inbound "chose: …" reply badge (AC-12-14) + unsupported
 * placeholder (AC-12-17).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationMessage } from '@/types/omnichannel';

import { Composer } from './composer';
import { MessageBubble } from './message-bubble';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));
vi.mock('@/lib/api-client', () => ({
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
}));

if (!('createObjectURL' in URL)) {
  // @ts-expect-error test shim
  URL.createObjectURL = () => 'blob:mock';
  // @ts-expect-error test shim
  URL.revokeObjectURL = () => {};
}

const baseComposer = {
  windowOpen: true,
  templates: [],
  quickReplies: [],
  isSending: false,
  sendError: null,
  onSend: vi.fn(async () => true),
  onSendTemplate: vi.fn(async () => true),
};

function msg(over: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: 'm1', contactId: 'c1', channelId: 'ch1',
    senderType: 'CONTACT', senderId: null, senderName: null,
    messageType: 'TEXT', body: null,
    mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
    reactions: [],
    externalMessageId: null, deliveryStatus: null, errorCode: null, errorMessage: null,
    replyTo: null, createdAt: '2026-07-07T10:00:00Z',
    ...over,
  };
}

describe('structured composer', () => {
  it('builds + sends reply-buttons interactive', async () => {
    const user = userEvent.setup();
    const onSendInteractive = vi.fn(async () => true);
    render(<Composer {...baseComposer} onSendInteractive={onSendInteractive} />);

    await user.click(screen.getByTestId('attach-menu'));
    await user.click(screen.getByTestId('attach-interactive'));
    await user.type(screen.getByTestId('interactive-body'), 'Pick one');
    await user.type(screen.getByTestId('interactive-button'), 'Yes');
    await user.click(screen.getByTestId('interactive-send'));

    await waitFor(() => expect(onSendInteractive).toHaveBeenCalledTimes(1));
    const arg = onSendInteractive.mock.calls[0][0] as {
      definition: { kind: string; body: string; buttons: { title: string }[] };
    };
    expect(arg.definition.kind).toBe('buttons');
    expect(arg.definition.body).toBe('Pick one');
    expect(arg.definition.buttons[0].title).toBe('Yes');
  });

  it('builds + sends a location', async () => {
    const user = userEvent.setup();
    const onSendLocation = vi.fn(async () => true);
    render(<Composer {...baseComposer} onSendLocation={onSendLocation} />);

    await user.click(screen.getByTestId('attach-menu'));
    await user.click(screen.getByTestId('attach-location'));
    await user.type(screen.getByTestId('location-lat'), '3.15');
    await user.type(screen.getByTestId('location-lng'), '101.7');
    await user.click(screen.getByTestId('location-send'));

    await waitFor(() => expect(onSendLocation).toHaveBeenCalledTimes(1));
    const arg = onSendLocation.mock.calls[0][0] as { lat: number; lng: number };
    expect(arg.lat).toBe(3.15);
    expect(arg.lng).toBe(101.7);
  });

  it('builds + sends a contact card', async () => {
    const user = userEvent.setup();
    const onSendContacts = vi.fn(async () => true);
    render(<Composer {...baseComposer} onSendContacts={onSendContacts} />);

    await user.click(screen.getByTestId('attach-menu'));
    await user.click(screen.getByTestId('attach-contact'));
    await user.type(screen.getByTestId('contact-name'), 'Jane Doe');
    await user.type(screen.getByTestId('contact-phone'), '+60123');
    await user.click(screen.getByTestId('contact-send'));

    await waitFor(() => expect(onSendContacts).toHaveBeenCalledTimes(1));
    const arg = onSendContacts.mock.calls[0][0] as { contacts: { phones: { phone: string }[] }[] };
    expect(arg.contacts[0].phones[0].phone).toBe('+60123');
  });
});

describe('structured bubbles', () => {
  it('renders interactive buttons preview', () => {
    render(
      <MessageBubble
        message={msg({
          senderType: 'AGENT',
          messageType: 'INTERACTIVE',
          payload: { kind: 'buttons', body: 'Pick', buttons: [{ id: 'y', title: 'Yes' }] },
        })}
      />,
    );
    expect(screen.getByTestId('structured-interactive')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
  });

  it('renders inbound reply badge', () => {
    render(
      <MessageBubble
        message={msg({
          messageType: 'INTERACTIVE_REPLY',
          payload: { kind: 'button', id: 'y', title: 'Yes' },
        })}
      />,
    );
    expect(screen.getByTestId('structured-reply')).toHaveTextContent('chose: Yes');
  });

  it('renders a location card with a maps link', () => {
    render(
      <MessageBubble
        message={msg({
          messageType: 'LOCATION',
          payload: { lat: 1.3, lng: 103.8, name: 'Home', address: null },
        })}
      />,
    );
    const link = screen.getByText('Open in Maps').closest('a');
    expect(link).toHaveAttribute('href', expect.stringContaining('1.3,103.8'));
  });

  it('renders a contact card with tel + vCard', () => {
    render(
      <MessageBubble
        message={msg({
          messageType: 'CONTACTS',
          payload: { contacts: [{ name: { formatted_name: 'Bob' }, phones: [{ phone: '+60199' }] }] },
        })}
      />,
    );
    expect(screen.getByText('+60199').closest('a')).toHaveAttribute('href', 'tel:+60199');
    expect(screen.getByText('Save contact').closest('a')).toHaveAttribute(
      'href',
      expect.stringContaining('text/vcard'),
    );
  });

  it('renders an unsupported placeholder', () => {
    render(<MessageBubble message={msg({ messageType: 'UNSUPPORTED' })} />);
    expect(screen.getByTestId('structured-unsupported')).toBeInTheDocument();
  });
});

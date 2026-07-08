/**
 * Plan 12 Slice 3 (frontend): reaction chips render on a bubble + the react
 * control fires onReact with the picked emoji (or '' to remove). AC-12-20.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationMessage } from '@/types/omnichannel';

import { MessageBubble } from './message-bubble';

function msg(over: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'm1', contactId: 'c1', channelId: 'ch1',
    senderType: 'CONTACT', senderId: null, senderName: null,
    messageType: 'TEXT', body: 'hello',
    mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
    reactions: [],
    externalMessageId: null, deliveryStatus: null, errorCode: null, errorMessage: null,
    replyTo: null, createdAt: '2026-07-08T10:00:00Z',
    ...over,
  };
}

describe('reaction chips', () => {
  it('renders emoji chips with a count when the same emoji repeats', () => {
    render(
      <MessageBubble
        message={msg({
          reactions: [
            { emoji: '👍', reactorType: 'CONTACT', reactor: 'x' },
            { emoji: '👍', reactorType: 'AGENT', reactor: 'y' },
            { emoji: '❤️', reactorType: 'CONTACT', reactor: 'z' },
          ],
        })}
      />,
    );
    const chips = screen.getByTestId('reaction-chips');
    expect(chips).toHaveTextContent('👍');
    expect(chips).toHaveTextContent('2'); // 👍 count
    expect(chips).toHaveTextContent('❤️');
  });

  it('does not render the chip row when there are no reactions', () => {
    render(<MessageBubble message={msg()} />);
    expect(screen.queryByTestId('reaction-chips')).toBeNull();
  });

  it('fires onReact with the picked emoji', async () => {
    const user = userEvent.setup();
    const onReact = vi.fn();
    render(<MessageBubble message={msg()} onReact={onReact} />);
    // Open the WhatsApp-style context menu on the bubble.
    await user.pointer({ keys: '[MouseRight]', target: screen.getByTestId('bubble-contact') });
    await user.click(await screen.findByTestId('react-👍'));
    expect(onReact).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), '👍');
  });

  it('offers a remove control when the agent already reacted', async () => {
    const user = userEvent.setup();
    const onReact = vi.fn();
    render(
      <MessageBubble
        message={msg({ reactions: [{ emoji: '🔥', reactorType: 'AGENT', reactor: 'me' }] })}
        onReact={onReact}
      />,
    );
    await user.pointer({ keys: '[MouseRight]', target: screen.getByTestId('bubble-contact') });
    await user.click(await screen.findByTestId('react-remove'));
    expect(onReact).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), '');
  });
});

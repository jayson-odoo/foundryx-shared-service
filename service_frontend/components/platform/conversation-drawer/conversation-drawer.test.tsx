/**
 * ConversationDrawer pieces (plan 05 Phase A): bubble rendering by sender_type,
 * delivery ticks, CSW composer lock, quick-reply insertion.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConversationMessage, QuickReply, WhatsAppTemplate } from '@/types/omnichannel';

import { Composer } from './composer';
import { ConversationDrawer, dayLabel } from './conversation-drawer';
import { HighlightedText, MessageBubble } from './message-bubble';

// useDatetime reads the session tz preference (plan sprint-2/05) — no
// preference here, so formatters fall back to the runner's browser tz.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

// Pin the drawer + hooks to the mock service (the binding is real since Phase B).
vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } = await import('@/services/conversation-service.mock');
  return { conversationService: mockConversationService };
});
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { getMembers: vi.fn(async () => []) },
}));

function msg(over: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-1',
    contactId: 'cnt-001',
    channelId: 'chn-001',
    senderType: 'CONTACT',
    senderId: null,
    senderName: null,
    messageType: 'TEXT',
    body: 'Hello there',
    mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false,
    externalMessageId: null,
    deliveryStatus: null,
    errorCode: null,
    errorMessage: null,
    replyTo: null,
    createdAt: '2026-06-04T10:00:00Z',
    ...over,
  };
}

const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: 'tpl-1', channelId: 'chn-001', name: 'booking_update', language: 'en',
    category: 'UTILITY', status: 'APPROVED',
    bodyText: 'Hi {{1}}, update: {{2}}.', variableCount: 2,
  },
];
const QUICK: QuickReply[] = [
  { id: 'qr-1', workspaceId: 'wsp-001', shortcut: '/hi', body: 'Hi! How can I help?' },
];

describe('MessageBubble', () => {
  it('renders CONTACT messages left-aligned', () => {
    render(<MessageBubble message={msg()} />);
    expect(screen.getByTestId('bubble-contact')).toBeInTheDocument();
    expect(screen.getByText('Hello there')).toBeInTheDocument();
  });

  it('renders AGENT messages with delivery ticks', () => {
    render(<MessageBubble message={msg({ senderType: 'AGENT', deliveryStatus: 'SENT' })} />);
    expect(screen.getByTestId('bubble-agent')).toBeInTheDocument();
    expect(screen.getByTestId('tick-sent')).toBeInTheDocument();
  });

  it('shows read ticks distinctly from delivered', () => {
    const { rerender } = render(<MessageBubble message={msg({ senderType: 'AGENT', deliveryStatus: 'DELIVERED' })} />);
    expect(screen.getByTestId('tick-delivered')).toBeInTheDocument();
    rerender(<MessageBubble message={msg({ senderType: 'AGENT', deliveryStatus: 'READ' })} />);
    expect(screen.getByTestId('tick-read')).toBeInTheDocument();
  });

  it('renders FAILED with the error reason', () => {
    render(
      <MessageBubble
        message={msg({
          senderType: 'AGENT',
          deliveryStatus: 'FAILED',
          errorMessage: 'Re-engagement message — 24h window has passed.',
        })}
      />,
    );
    expect(screen.getByTestId('tick-failed')).toBeInTheDocument();
    expect(screen.getByTestId('bubble-error')).toHaveTextContent('24h window');
  });

  it('renders SYSTEM as a centered internal note', () => {
    render(<MessageBubble message={msg({ senderType: 'SYSTEM', senderName: 'Demo User', body: 'VIP client' })} />);
    expect(screen.getByTestId('bubble-system')).toBeInTheDocument();
    expect(screen.getByText(/Internal note/)).toBeInTheDocument();
  });

  it('labels TEMPLATE messages', () => {
    render(<MessageBubble message={msg({ senderType: 'AGENT', messageType: 'TEMPLATE', deliveryStatus: 'SENT' })} />);
    expect(screen.getByText('Template')).toBeInTheDocument();
  });
});

describe('Composer — CSW lock (decision 14)', () => {
  const base = {
    templates: TEMPLATES,
    quickReplies: QUICK,
    isSending: false,
    sendError: null,
    onSend: vi.fn(async () => true),
  };

  it('free-form enabled while the window is open', () => {
    render(<Composer {...base} windowOpen />);
    expect(screen.getByTestId('message-input')).toBeEnabled();
    expect(screen.queryByTestId('csw-banner')).not.toBeInTheDocument();
  });

  it('locks the input and offers the template picker when closed', async () => {
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen={false} />);
    expect(screen.getByTestId('message-input')).toBeDisabled();
    expect(screen.getByTestId('csw-banner')).toBeInTheDocument();

    await user.click(screen.getByTestId('csw-pick-template'));
    expect(screen.getByText('Send a template')).toBeInTheDocument();
  });

  it('template send requires every variable, then sends', async () => {
    const onSend = vi.fn(async () => true);
    const user = userEvent.setup();
    render(<Composer {...base} onSend={onSend} windowOpen={false} />);

    await user.click(screen.getByTestId('csw-pick-template'));
    await user.click(screen.getByRole('combobox', { name: 'Template' }));
    await user.click(await screen.findByRole('option', { name: /booking_update/ }));
    expect(screen.getByTestId('template-send')).toBeDisabled();

    await user.type(screen.getByTestId('template-var-1'), 'Marcus');
    await user.type(screen.getByTestId('template-var-2'), 'slot moved');
    expect(screen.getByTestId('template-preview')).toHaveTextContent('Hi Marcus, update: slot moved.');

    await user.click(screen.getByTestId('template-send'));
    expect(onSend).toHaveBeenCalledWith({
      messageType: 'TEMPLATE',
      templateId: 'tpl-1',
      templateVariables: ['Marcus', 'slot moved'],
    });
  });

  it('sends free-form on Enter', async () => {
    const onSend = vi.fn(async () => true);
    const user = userEvent.setup();
    render(<Composer {...base} onSend={onSend} windowOpen />);

    await user.type(screen.getByTestId('message-input'), 'On it!{Enter}');
    expect(onSend).toHaveBeenCalledWith({ messageType: 'TEXT', body: 'On it!' });
  });

  it('inserts a quick reply into the input', async () => {
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen />);

    await user.click(screen.getByTestId('quick-replies'));
    await user.click(await screen.findByText('Hi! How can I help?'));
    expect(screen.getByTestId('message-input')).toHaveValue('Hi! How can I help?');
  });

  it('note mode bypasses the CSW lock', () => {
    const onAddNote = vi.fn(async () => true);
    render(<Composer {...base} windowOpen={false} mode="note" onAddNote={onAddNote} />);
    expect(screen.getByTestId('note-input')).toBeEnabled();
    expect(screen.queryByTestId('csw-banner')).not.toBeInTheDocument();
  });

  it('reply strip shows the quoted message and the send carries replyToMessageId', async () => {
    const onSend = vi.fn(async () => true);
    const onCancelReply = vi.fn();
    const user = userEvent.setup();
    render(
      <Composer
        {...base}
        onSend={onSend}
        windowOpen
        replyTo={msg({ id: 'msg-7', body: 'Can I change my booking?' })}
        onCancelReply={onCancelReply}
      />,
    );

    expect(screen.getByTestId('reply-strip')).toHaveTextContent('Can I change my booking?');

    await user.type(screen.getByTestId('message-input'), 'Yes, no problem!{Enter}');
    expect(onSend).toHaveBeenCalledWith({
      messageType: 'TEXT',
      body: 'Yes, no problem!',
      replyToMessageId: 'msg-7',
    });
    expect(onCancelReply).toHaveBeenCalled(); // strip clears after a send
  });

  it('cancel button clears the reply strip', async () => {
    const onCancelReply = vi.fn();
    const user = userEvent.setup();
    render(<Composer {...base} windowOpen replyTo={msg()} onCancelReply={onCancelReply} />);
    await user.click(screen.getByTestId('reply-cancel'));
    expect(onCancelReply).toHaveBeenCalled();
  });
});

describe('MessageBubble — quoted replies + context menu', () => {
  it('renders the quoted block on a reply message', () => {
    render(
      <MessageBubble
        message={msg({
          senderType: 'AGENT',
          deliveryStatus: 'SENT',
          body: 'Yes, moved it!',
          replyTo: { id: 'msg-0', body: 'Can I change my booking?', senderType: 'CONTACT', senderName: null },
        })}
        contactName="Sarah Chen"
      />,
    );
    const quoted = screen.getByTestId('quoted-block');
    expect(quoted).toHaveTextContent('Sarah Chen');
    expect(quoted).toHaveTextContent('Can I change my booking?');
  });

  it('right-click opens the menu; Reply fires onReply', async () => {
    const onReply = vi.fn();
    const user = userEvent.setup();
    render(<MessageBubble message={msg()} onReply={onReply} />);

    await user.pointer({ keys: '[MouseRight]', target: screen.getByTestId('bubble-contact') });
    await user.click(await screen.findByTestId('menu-reply'));
    expect(onReply).toHaveBeenCalledWith(expect.objectContaining({ id: 'msg-1' }));
  });

  it('Copy message writes the body to the clipboard', async () => {
    const user = userEvent.setup(); // userEvent stubs navigator.clipboard in jsdom
    render(<MessageBubble message={msg({ body: 'Copy me' })} onReply={vi.fn()} />);

    await user.pointer({ keys: '[MouseRight]', target: screen.getByTestId('bubble-contact') });
    await user.click(await screen.findByTestId('menu-copy'));
    expect(await navigator.clipboard.readText()).toBe('Copy me');
  });
});

describe('HighlightedText', () => {
  it('marks case-insensitive occurrences', () => {
    render(<HighlightedText text="Booking the booking hall" term="booking" />);
    expect(screen.getAllByText(/booking/i, { selector: 'mark' })).toHaveLength(2);
  });

  it('renders plain text without a term', () => {
    render(<HighlightedText text="No marks here" />);
    expect(screen.getByText('No marks here')).toBeInTheDocument();
    expect(document.querySelector('mark')).toBeNull();
  });

  it('escapes regex special characters in the term', () => {
    render(<HighlightedText text="cost is $50 (deposit)" term="$50 (deposit)" />);
    expect(screen.getByText('$50 (deposit)', { selector: 'mark' })).toBeInTheDocument();
  });
});

describe('ConversationDrawer — in-thread search', () => {
  beforeEach(async () => {
    const { __mockResetConversations } = await import('@/services/conversation-service.mock');
    __mockResetConversations();
    // jsdom lacks scrollIntoView.
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('searches within the thread, counts matches, navigates with Enter', async () => {
    const user = userEvent.setup();
    render(<ConversationDrawer contactId="cnt-001" />);
    await waitFor(() => expect(screen.getByTestId('thread-window')).toBeInTheDocument());

    await user.click(screen.getByTestId('thread-search-toggle'));
    await user.type(screen.getByTestId('thread-search-input'), 'booking');

    // cnt-001 seed: "...booked..." no; bodies with "booking": 2 messages.
    await waitFor(() =>
      expect(screen.getByTestId('thread-search-count').textContent).toMatch(/^[12] \/ \d+$/),
    );
    const [cursor, total] = screen
      .getByTestId('thread-search-count')
      .textContent!.split('/')
      .map((s) => parseInt(s.trim(), 10));
    expect(total).toBeGreaterThanOrEqual(2);
    expect(cursor).toBe(1);

    // Enter steps to the older match.
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('thread-search-count').textContent).toContain('2 /');

    // Matched text is highlighted.
    expect(document.querySelectorAll('mark').length).toBeGreaterThan(0);

    // Close clears highlights.
    await user.click(screen.getByTestId('thread-search-close'));
    expect(screen.queryByTestId('thread-search-bar')).not.toBeInTheDocument();
    expect(document.querySelectorAll('mark').length).toBe(0);
  });
});

describe('dayLabel', () => {
  it('maps today/yesterday/older correctly', () => {
    // Pin the viewer tz to UTC so the naive-UTC inputs land on known days.
    const now = new Date('2026-06-05T12:00:00Z');
    expect(dayLabel('2026-06-05T08:00:00', now, 'UTC')).toBe('Today');
    expect(dayLabel('2026-06-04T23:59:00', now, 'UTC')).toBe('Yesterday');
    expect(dayLabel('2026-06-01T10:00:00', now, 'UTC')).toMatch(
      /1 June 2026|June 1, 2026/,
    );
  });

  it('resolves the day in the viewer tz, not UTC', () => {
    const now = new Date('2026-06-05T12:00:00Z');
    // 23:30 UTC on the 4th = already the 5th in Tokyo → Today there.
    expect(dayLabel('2026-06-04T23:30:00', now, 'Asia/Tokyo')).toBe('Today');
    expect(dayLabel('2026-06-04T23:30:00', now, 'UTC')).toBe('Yesterday');
  });
});

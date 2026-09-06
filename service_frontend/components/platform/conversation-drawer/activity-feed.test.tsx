/** AC-IVE-32/34/48 - merged feed ordering + note-vs-event rendering. */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ConversationEvent, ConversationMessage } from '@/types/omnichannel';
import { ActivityFeed } from './activity-feed';

function note(id: string, createdAt: string, body: string): ConversationMessage {
  return {
    id, contactId: 'cnt-1', channelId: null, senderType: 'SYSTEM', senderId: 'usr-demo', senderName: 'Demo User',
    messageType: 'TEXT', body, mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false,
    payload: null, reactions: [], externalMessageId: null, deliveryStatus: null, errorCode: null, errorMessage: null,
    replyTo: null, createdAt,
  };
}

function event(id: string, createdAt: string, over: Partial<ConversationEvent> = {}): ConversationEvent {
  return {
    id, eventType: 'opened', actorName: 'Demo User', actorUserId: 'usr-demo', fromValue: null, fromLabel: null,
    toValue: null, toLabel: null, closeReasonId: null, closeReasonName: null, note: null, payload: null,
    createdAt, ...over,
  };
}

const formatTime = (iso: string) => iso.slice(11, 16);

describe('ActivityFeed', () => {
  it('shows an empty state with no notes and no events', () => {
    render(<ActivityFeed messages={[]} events={[]} contactName="Sarah" formatTime={formatTime} />);
    expect(screen.getByText('No activity yet.')).toBeInTheDocument();
  });

  it('merges notes and events in chronological order', () => {
    const messages = [note('m1', '2026-01-01T10:00:00Z', 'VIP - handle with care')];
    const events = [
      event('e1', '2026-01-01T09:00:00Z', { eventType: 'opened', actorName: null }),
      event('e2', '2026-01-01T11:00:00Z', { eventType: 'assigned', toLabel: 'Demo User' }),
    ];
    render(<ActivityFeed messages={messages} events={events} contactName="Sarah" formatTime={formatTime} />);
    const feed = screen.getByTestId('activity-feed');
    const text = feed.textContent ?? '';
    expect(text.indexOf('Conversation opened')).toBeLessThan(text.indexOf('VIP - handle with care'));
    expect(text.indexOf('VIP - handle with care')).toBeLessThan(text.indexOf('assigned to Demo User'));
  });

  it('renders a note as an authored bubble and an event as a compact system line', () => {
    render(
      <ActivityFeed
        messages={[note('m1', '2026-01-01T10:00:00Z', 'Internal note body')]}
        events={[event('e1', '2026-01-01T09:00:00Z', { eventType: 'opened', actorName: null })]}
        contactName="Sarah"
        formatTime={formatTime}
      />,
    );
    expect(screen.getByText('Internal note body')).toBeInTheDocument();
    expect(screen.getByTestId('event-opened')).toBeInTheDocument();
  });

  it('does NOT render a comment_added event as a duplicate line next to its note (AC-IVE-34)', () => {
    render(
      <ActivityFeed
        messages={[note('m1', '2026-01-01T10:00:00Z', 'A fresh note')]}
        events={[event('e1', '2026-01-01T10:00:00Z', { eventType: 'comment_added', payload: { messageId: 'm1' } })]}
        contactName="Sarah"
        formatTime={formatTime}
      />,
    );
    expect(screen.getByText('A fresh note')).toBeInTheDocument();
    expect(screen.queryByTestId('event-comment_added')).not.toBeInTheDocument();
  });

  // F7 (round-3 codex triage) - a lexicographic string sort misorders ISO
  // timestamps with different fractional-second precision. Python's
  // `isoformat()` drops the fractional part ENTIRELY at exactly-zero
  // microseconds, so a same-second-but-LATER event with a fractional part
  // (`.5` = 500ms) can carry a STRING that sorts BEFORE a same-second
  // whole-second event with no fractional part at all ('.' < 'Z'
  // character-by-character) even though it happened after.
  it('sorts by numeric epoch, not ISO string, across mixed fractional-second precision', () => {
    const messages = [note('m1', '2026-01-01T10:00:00.500000Z', 'Later note (fractional seconds)')];
    const events = [
      event('e1', '2026-01-01T10:00:00Z', { eventType: 'opened', actorName: null }),
    ];
    render(<ActivityFeed messages={messages} events={events} contactName="Sarah" formatTime={formatTime} />);
    const feed = screen.getByTestId('activity-feed');
    const text = feed.textContent ?? '';
    // The whole-second event (no fractional part, numerically EARLIER) must
    // render BEFORE the .5s-later note - a lexicographic sort gets this
    // backwards (the '.' character sorts before 'Z').
    expect(text.indexOf('Conversation opened')).toBeLessThan(
      text.indexOf('Later note (fractional seconds)'),
    );
  });

  it('renders a close event with its reason', () => {
    render(
      <ActivityFeed
        messages={[]}
        events={[event('e1', '2026-01-01T10:00:00Z', { eventType: 'closed', closeReasonName: 'Payment Issue' })]}
        contactName="Sarah"
        formatTime={formatTime}
      />,
    );
    expect(screen.getByText(/closed this conversation - Payment Issue/)).toBeInTheDocument();
  });
});

/**
 * WS `broadcast.updated` reconciliation (plan 29 S4, AC-BRD-13/45) - the
 * detail view's live-refresh handler is a thin wrapper around this pure
 * matcher, so the reconciliation logic itself is unit-testable without
 * mounting the socket, the form, or the recipients list.
 */
import { describe, expect, it } from 'vitest';
import type { ConversationSocketEvent } from '@/types/omnichannel';
import { matchBroadcastUpdate } from './broadcast-realtime';

const COUNTS = { total: 10, sent: 4, delivered: 3, read: 1, failed: 1, skipped: 1 };

function updateEvent(broadcastId: string): ConversationSocketEvent {
  return { type: 'broadcast.updated', broadcastId, status: 'SENDING', counts: COUNTS };
}

describe('matchBroadcastUpdate', () => {
  it('returns the status/counts update for a matching broadcast id', () => {
    const result = matchBroadcastUpdate(updateEvent('bcst-1'), 'bcst-1');
    expect(result).toEqual({ status: 'SENDING', counts: COUNTS });
  });

  it('ignores an update for a DIFFERENT broadcast (another campaign in the same workspace)', () => {
    expect(matchBroadcastUpdate(updateEvent('bcst-2'), 'bcst-1')).toBeNull();
  });

  it('ignores every other socket event type (message.status, …)', () => {
    const messageStatus: ConversationSocketEvent = {
      type: 'message.status',
      messageId: 'msg-1',
      contactId: 'cnt-1',
      deliveryStatus: 'DELIVERED',
    };
    expect(matchBroadcastUpdate(messageStatus, 'bcst-1')).toBeNull();
  });

  it('returns null while no broadcast is open yet (id null/undefined - create mode, or still loading)', () => {
    expect(matchBroadcastUpdate(updateEvent('bcst-1'), null)).toBeNull();
    expect(matchBroadcastUpdate(updateEvent('bcst-1'), undefined)).toBeNull();
  });
});

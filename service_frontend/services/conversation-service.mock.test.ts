/**
 * Mock conversation service contract tests (plan 05 Phase A).
 * The CSW rule mirrored here is the backend invariant Phase B enforces for real.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MOCK_CURRENT_USER,
  __mockResetConversations,
  __mockSimulateInbound,
  mockConversationService as svc,
} from './conversation-service.mock';

beforeEach(() => {
  __mockResetConversations();
});

describe('listThreads', () => {
  it('sorts by lastMessageAt desc', async () => {
    const list = await svc.listThreads({ workspaceId: 'wsp-001' });
    const times = list.map((t) => t.lastMessageAt ?? '');
    expect([...times].sort().reverse()).toEqual(times);
  });

  it('filters the unassigned bucket', async () => {
    const list = await svc.listThreads({ assignee: 'unassigned' });
    expect(list.length).toBeGreaterThan(0);
    expect(list.every((t) => t.assignedUserId === null)).toBe(true);
  });

  it('filters mine', async () => {
    const list = await svc.listThreads({ assignee: 'me' });
    expect(list.length).toBeGreaterThan(0);
    expect(list.every((t) => t.assignedUserId === MOCK_CURRENT_USER.id)).toBe(true);
  });
});

describe('sendMessage - CSW enforcement (decision 14)', () => {
  it('allows free-form inside the 24h window', async () => {
    const msg = await svc.sendMessage('cnt-001', { messageType: 'TEXT', body: 'Hello!' });
    expect(msg.senderType).toBe('AGENT');
    expect(msg.deliveryStatus).toBe('SENT');
  });

  it('rejects free-form once the window has closed', async () => {
    await expect(
      svc.sendMessage('cnt-002', { messageType: 'TEXT', body: 'Hello?' }),
    ).rejects.toThrow(/24-hour window/);
  });

  it('allows an approved template outside the window, with variables filled', async () => {
    const msg = await svc.sendMessage('cnt-002', {
      messageType: 'TEMPLATE',
      templateId: 'tpl-001',
      templateVariables: ['Marcus', 'your slot moved to 4pm'],
    });
    expect(msg.messageType).toBe('TEMPLATE');
    expect(msg.body).toContain('Hi Marcus');
    expect(msg.body).toContain('your slot moved to 4pm');
  });

  it('resolves replyToMessageId into a quoted ReplyRef', async () => {
    const history = await svc.listMessages('cnt-001');
    const target = history.find((m) => m.senderType === 'CONTACT')!;

    const msg = await svc.sendMessage('cnt-001', {
      messageType: 'TEXT',
      body: 'Replying to you',
      replyToMessageId: target.id,
    });
    expect(msg.replyTo).toEqual({
      id: target.id,
      body: target.body,
      senderType: 'CONTACT',
      senderName: target.senderName,
    });
  });

  it('rejects a non-approved template', async () => {
    await expect(
      svc.sendMessage('cnt-002', { messageType: 'TEMPLATE', templateId: 'tpl-003', templateVariables: ['x'] }),
    ).rejects.toThrow(/not approved/i);
  });
});

describe('internal notes', () => {
  it('creates a SYSTEM bubble that has no delivery status', async () => {
    const note = await svc.addInternalNote('cnt-001', 'Escalate to manager');
    expect(note.senderType).toBe('SYSTEM');
    expect(note.deliveryStatus).toBeNull();
    expect(note.externalMessageId).toBeNull();
  });
});

describe('assignment + lifecycle', () => {
  it('self-claim assigns the current user', async () => {
    const t = await svc.assign('cnt-003', MOCK_CURRENT_USER.id);
    expect(t.assignedUserId).toBe(MOCK_CURRENT_USER.id);
    expect(t.assignedUserName).toBe(MOCK_CURRENT_USER.name);
  });

  it('unassign clears the assignee', async () => {
    const t = await svc.assign('cnt-001', null);
    expect(t.assignedUserId).toBeNull();
  });

  it('snooze/close transition status', async () => {
    expect((await svc.setStatus('cnt-001', 'SNOOZED')).status).toBe('SNOOZED');
    expect((await svc.setStatus('cnt-001', 'CLOSED')).status).toBe('CLOSED');
  });
});

describe('templates + quick replies', () => {
  it('only returns APPROVED templates', async () => {
    const list = await svc.listTemplates('chn-001');
    expect(list.length).toBeGreaterThan(0);
    expect(list.every((t) => t.status === 'APPROVED')).toBe(true);
  });

  it('returns workspace quick replies', async () => {
    const list = await svc.listQuickReplies('wsp-001');
    expect(list.length).toBeGreaterThan(0);
  });
});

describe('realtime emitter', () => {
  it('delivers message.created to subscribers and re-opens the thread', async () => {
    const handler = vi.fn();
    const unsub = svc.subscribe('wsp-001', handler);

    await svc.setStatus('cnt-001', 'CLOSED');
    handler.mockClear();

    __mockSimulateInbound('wsp-001', 'cnt-001');

    expect(handler).toHaveBeenCalledTimes(1);
    const event = handler.mock.calls[0][0];
    expect(event.type).toBe('message.created');
    expect(event.thread.status).toBe('OPEN'); // inbound re-opens
    expect(event.thread.unreadCount).toBeGreaterThan(0);

    unsub();
    __mockSimulateInbound('wsp-001', 'cnt-001');
    expect(handler).toHaveBeenCalledTimes(1); // unsubscribed - no more calls
  });

  it('ticks delivery receipts SENT→DELIVERED→READ after a send', async () => {
    vi.useFakeTimers();
    try {
      const handler = vi.fn();
      svc.subscribe('wsp-001', handler);

      const sendPromise = svc.sendMessage('cnt-001', { messageType: 'TEXT', body: 'ping' });
      await vi.advanceTimersByTimeAsync(300); // resolve the mock latency
      const msg = await sendPromise;
      expect(msg.deliveryStatus).toBe('SENT');

      await vi.advanceTimersByTimeAsync(1_500);
      await vi.advanceTimersByTimeAsync(2_500);

      const statusEvents = handler.mock.calls
        .map((c) => c[0])
        .filter((e) => e.type === 'message.status' && e.messageId === msg.id);
      expect(statusEvents.map((e) => e.deliveryStatus)).toEqual(['DELIVERED', 'READ']);
    } finally {
      vi.useRealTimers();
    }
  });
});

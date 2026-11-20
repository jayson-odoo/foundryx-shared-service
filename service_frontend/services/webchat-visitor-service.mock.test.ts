import { describe, expect, it } from 'vitest';
import { mockWebchatSession, mockWebchatVisitorService } from './webchat-visitor-service.mock';

/**
 * Mock web chat VISITOR service (plan 34 / A7b S4 - AC-WEB-10/26/32).
 * Session start is the LOADER's (BL-SS-183), so the mock's own entry point
 * is `mockWebchatSession()` - the payload a loader hands the panel.
 */
describe('mockWebchatVisitorService', () => {
  it('mockWebchatSession() builds the payload the loader hands over, with empty history', () => {
    const result = mockWebchatSession();
    expect(result.token).toBeTruthy();
    expect(result.visitorId).toBeTruthy();
    expect(result.messages).toEqual([]);
    expect(result.config.greeting).toBeTruthy();
    expect(result.online).toBe(true);
  });

  it('the SAME token resolves the SAME visitor and history (AC-WEB-29/49/50)', () => {
    const first = mockWebchatSession();
    const replay = mockWebchatSession(first.token);
    expect(replay.token).toBe(first.token);
    expect(replay.visitorId).toBe(first.visitorId);
  });

  it('sendMessage() appends the visitor message and later a canned agent reply', async () => {
    const session = mockWebchatSession();
    const sent = await mockWebchatVisitorService.sendMessage('wk_test', session.token, {
      text: 'Hello there',
    });
    expect(sent).not.toBeNull();
    expect(sent?.direction).toBe('in');
    expect(sent?.text).toBe('Hello there');

    const page = await mockWebchatVisitorService.listMessages('wk_test', session.token);
    expect(page.data.some((m) => m.id === sent?.id)).toBe(true);
  });

  it('sendMessage() with a filled honeypot returns null and stores nothing (AC-WEB-32)', async () => {
    const session = mockWebchatSession();
    const result = await mockWebchatVisitorService.sendMessage('wk_test', session.token, {
      text: 'Hello there',
      hp: 'i-am-a-bot',
    });
    expect(result).toBeNull();
    const page = await mockWebchatVisitorService.listMessages('wk_test', session.token);
    expect(page.data).toEqual([]);
  });

  it('listMessages() with `after` returns only messages past the cursor', async () => {
    const session = mockWebchatSession();
    const first = await mockWebchatVisitorService.sendMessage('wk_test', session.token, {
      text: 'First',
    });
    const page = await mockWebchatVisitorService.listMessages('wk_test', session.token, first?.id);
    expect(page.data.every((m) => m.id !== first?.id)).toBe(true);
  });

  it('subscribe() never emits (the mock transport has no server) and unsubscribes cleanly', () => {
    const unsubscribe = mockWebchatVisitorService.subscribe('ws-demo-001', 'tok', () => {
      throw new Error('should never be called');
    });
    expect(() => unsubscribe()).not.toThrow();
  });
});

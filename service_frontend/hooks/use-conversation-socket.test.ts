/**
 * Owner's local check: once the live feed is back after a drop, the inbox
 * fetches again for what it missed (`onResume`); the first connect does not.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useConversationSocket } from './use-conversation-socket';

const { subscribe } = vi.hoisted(() => ({ subscribe: vi.fn() }));
vi.mock('@/services/conversation-service', () => ({ conversationService: { subscribe } }));

describe('useConversationSocket', () => {
  it('reports each change and runs onResume only when the feed comes back after a drop', () => {
    let report: (connected: boolean) => void = () => {};
    subscribe.mockImplementation((_id: string, _handler: unknown, onChange: (c: boolean) => void) => {
      report = onChange;
      return () => {};
    });
    const changes: boolean[] = [];
    const onResume = vi.fn();
    renderHook(() => useConversationSocket('ws-1', () => {}, (c) => changes.push(c), onResume));

    report(true);
    expect(onResume).not.toHaveBeenCalled();
    report(false);
    report(true);
    expect(onResume).toHaveBeenCalledTimes(1);
    report(true);
    expect(onResume).toHaveBeenCalledTimes(1);
    expect(changes).toEqual([true, false, true, true]);
  });
});

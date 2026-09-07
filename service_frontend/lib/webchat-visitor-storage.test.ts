import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  __resetWebchatVisitorStorageForTests,
  clearVisitorToken,
  readVisitorToken,
  writeVisitorToken,
} from './webchat-visitor-storage';

describe('webchat visitor token storage (AC-WEB-49/50)', () => {
  afterEach(() => {
    __resetWebchatVisitorStorageForTests();
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('round-trips a token through localStorage, scoped per widget key', () => {
    writeVisitorToken('wk_a', 'token-a');
    writeVisitorToken('wk_b', 'token-b');
    expect(readVisitorToken('wk_a')).toBe('token-a');
    expect(readVisitorToken('wk_b')).toBe('token-b');
  });

  it('returns null for a widget key with no stored token', () => {
    expect(readVisitorToken('wk_never_seen')).toBeNull();
  });

  it('clearVisitorToken removes only that widget key', () => {
    writeVisitorToken('wk_a', 'token-a');
    writeVisitorToken('wk_b', 'token-b');
    clearVisitorToken('wk_a');
    expect(readVisitorToken('wk_a')).toBeNull();
    expect(readVisitorToken('wk_b')).toBe('token-b');
  });

  it('AC-WEB-49 - falls back to an in-memory session when storage throws, never throwing itself', () => {
    const setItem = vi.spyOn(window.localStorage.__proto__, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    __resetWebchatVisitorStorageForTests();

    expect(() => writeVisitorToken('wk_blocked', 'in-memory-token')).not.toThrow();
    expect(readVisitorToken('wk_blocked')).toBe('in-memory-token');

    setItem.mockRestore();
  });
});

/**
 * T7 carry-over C2: a rejected `writeText` used to only `console.error` -
 * the user saw nothing happen. `error` flips true (auto-clears after
 * `timeout`) so a consumer can render an inline, non-toast message.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useCopyToClipboard } from './use-copy-to-clipboard';

describe('useCopyToClipboard', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('sets isCopied true and error false on a successful copy, then clears isCopied after timeout', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    const { result } = renderHook(() => useCopyToClipboard({ timeout: 1000 }));

    await act(async () => {
      result.current.copyToClipboard('hello');
      await Promise.resolve();
    });

    expect(result.current.isCopied).toBe(true);
    expect(result.current.error).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.isCopied).toBe(false);
  });

  it('sets error true (not isCopied) when writeText rejects, and auto-clears after timeout', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    const { result } = renderHook(() => useCopyToClipboard({ timeout: 1000 }));

    await act(async () => {
      result.current.copyToClipboard('hello');
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.error).toBe(true);
    expect(result.current.isCopied).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.error).toBe(false);
  });

  it('a later successful copy clears a stale error', async () => {
    const writeText = vi.fn().mockRejectedValueOnce(new Error('denied')).mockResolvedValueOnce(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const { result } = renderHook(() => useCopyToClipboard({ timeout: 1000 }));

    await act(async () => {
      result.current.copyToClipboard('hello');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.error).toBe(true);

    await act(async () => {
      result.current.copyToClipboard('hello');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.error).toBe(false);
    expect(result.current.isCopied).toBe(true);
  });

  // Crew pass 70e96f2b: on a plain-HTTP page (not a secure context) the
  // browser has NO navigator.clipboard - the hook used to throw a TypeError
  // and show nothing. It now copies through a hidden textarea instead.
  it('copies without navigator.clipboard (insecure page) through the legacy copy', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const exec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
    const { result } = renderHook(() => useCopyToClipboard({ timeout: 1000 }));
    await act(async () => {
      result.current.copyToClipboard('hello');
      await Promise.resolve();
    });
    expect(exec).toHaveBeenCalledWith('copy');
    expect(result.current.isCopied).toBe(true);
    expect(result.current.error).toBe(false);
  });

  it('shows the error state, never throws, when no copy method works', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    Object.defineProperty(document, 'execCommand', { value: vi.fn().mockReturnValue(false), configurable: true });
    const { result } = renderHook(() => useCopyToClipboard({ timeout: 1000 }));
    await act(async () => {
      expect(() => result.current.copyToClipboard('hello')).not.toThrow();
      await Promise.resolve();
    });
    expect(result.current.isCopied).toBe(false);
    expect(result.current.error).toBe(true);
  });
});

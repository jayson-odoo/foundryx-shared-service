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
});

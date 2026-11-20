import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from './clipboard';

describe('copyText (crew pass 3208a91e: plain-http origin)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
  });

  it('copies with the browser copy command when navigator.clipboard is missing (not a secure context)', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
    await expect(copyText('https://host/in/abc')).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
    expect(document.querySelectorAll('textarea').length).toBe(0); // cleaned up
  });

  it('falls back when the Clipboard API refuses', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn(() => Promise.reject(new Error('denied'))) },
      configurable: true,
    });
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => true), configurable: true });
    await expect(copyText('k')).resolves.toBe(true);
  });

  it('answers false when nothing can copy', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true });
    await expect(copyText('k')).resolves.toBe(false);
  });
});

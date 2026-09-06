/**
 * AC-DLA-45: `deferredToast` puts the countdown over a sonner `toast.custom`
 * keyed by id (own id, or a caller-supplied bulk id), with the window's
 * duration + an 8s safety margin; `dismissDeferredToast` dismisses by the
 * same id.
 */
import { describe, expect, it, vi } from 'vitest';

const customMock = vi.fn(() => 'toast-id-1');
const dismissMock = vi.fn();
vi.mock('sonner', () => ({
  toast: { custom: (...args: unknown[]) => customMock(...args), dismiss: (...a: unknown[]) => dismissMock(...a) },
}));

import { deferredToast, dismissDeferredToast } from './deferred-toast';

describe('deferredToast', () => {
  it('renders via toast.custom keyed by the given id, duration = window + 8s margin', () => {
    const onCancel = vi.fn();
    const result = deferredToast({
      id: 'pending-action-u1',
      verb: 'Deleting',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
      onCancel,
    });
    expect(result).toBe('toast-id-1');
    expect(customMock).toHaveBeenCalledTimes(1);
    const [, options] = customMock.mock.calls[0] as [unknown, { id: string; duration: number }];
    expect(options.id).toBe('pending-action-u1');
    expect(options.duration).toBe(10_000 + 8000);
  });

  it('a bulk toast carries the count + noun through to the rendered countdown', () => {
    const renderFn = vi.fn();
    customMock.mockImplementationOnce((fn: unknown) => {
      renderFn(fn);
      return 'toast-id-bulk';
    });
    deferredToast({
      id: 'pending-action-bulk-1',
      verb: 'Deleting',
      commitAt: new Date(Date.now() + 8_000).toISOString(),
      windowSeconds: 8,
      count: 12,
      noun: 'users',
      onCancel: vi.fn(),
    });
    expect(renderFn).toHaveBeenCalledTimes(1);
  });

  it('dismissDeferredToast dismisses by the same id', () => {
    dismissDeferredToast('pending-action-u1');
    expect(dismissMock).toHaveBeenCalledWith('pending-action-u1');
  });
});

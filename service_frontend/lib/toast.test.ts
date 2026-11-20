/**
 * AC-DLA-51: `lib/toast.ts` sets the durations sonner does not default to -
 * success/info/warning clear at 4000ms, error waits (`Infinity` +
 * `closeButton`) - and passes `custom`/`dismiss` straight through.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const success = vi.fn();
const error = vi.fn();
const info = vi.fn();
const warning = vi.fn();
const custom = vi.fn();
const dismiss = vi.fn();
const message = vi.fn();

vi.mock('sonner', () => ({
  toast: { success, error, info, warning, custom, dismiss, message },
}));

describe('AC-DLA-51 lib/toast.ts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('success defaults to 4000ms and forwards overrides', async () => {
    const { toast } = await import('./toast');
    toast.success('Saved.');
    expect(success).toHaveBeenCalledWith('Saved.', { duration: 4000 });
    toast.success('Saved.', { duration: 1000 });
    expect(success).toHaveBeenLastCalledWith('Saved.', { duration: 1000 });
  });

  it('error stays until dismissed - duration Infinity + closeButton', async () => {
    const { toast } = await import('./toast');
    toast.error('Failed.');
    expect(error).toHaveBeenCalledWith('Failed.', { duration: Infinity, closeButton: true });
  });

  it('info and warning default to 4000ms', async () => {
    const { toast } = await import('./toast');
    toast.info('FYI.');
    expect(info).toHaveBeenCalledWith('FYI.', { duration: 4000 });
    toast.warning('Careful.');
    expect(warning).toHaveBeenCalledWith('Careful.', { duration: 4000 });
  });

  it('custom, dismiss and message pass straight through to sonner', async () => {
    const { toast } = await import('./toast');
    const jsx: Parameters<typeof toast.custom>[0] = () => null as never;
    toast.custom(jsx, { id: 'x' });
    expect(custom).toHaveBeenCalledWith(jsx, { id: 'x' });
    toast.dismiss('x');
    expect(dismiss).toHaveBeenCalledWith('x');
    toast.message('Plain toast.', { description: 'Detail.' });
    expect(message).toHaveBeenCalledWith('Plain toast.', { description: 'Detail.' });
  });
});

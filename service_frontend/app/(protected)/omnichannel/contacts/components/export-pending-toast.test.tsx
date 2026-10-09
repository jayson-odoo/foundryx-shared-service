/**
 * Nit 21 (review round 1): "View Jobs" navigates via the Next router
 * (`push`), never `window.location.assign` (a full page reload).
 */
import { describe, expect, it, vi } from 'vitest';

const toastInfo = vi.fn();
vi.mock('@/lib/toast', () => ({ toast: { info: (...a: unknown[]) => toastInfo(...a) } }));

import { exportPendingToast } from './export-pending-toast';

describe('exportPendingToast', () => {
  it('the "View Jobs" action calls the given router push, not window.location', () => {
    const push = vi.fn();
    exportPendingToast(push);

    expect(toastInfo).toHaveBeenCalledTimes(1);
    const [, options] = toastInfo.mock.calls[0] as [string, { action: { onClick: () => void } }];
    options.action.onClick();
    expect(push).toHaveBeenCalledWith('/jobs');
  });
});

/**
 * Round-3 codex triage F6 - Deactivate/Activate must surface a failure, not
 * silently discard `update()`'s rejection (`void update(...)`, no catch
 * anywhere in the chain: `useCloseReasons.update` re-throws, and the
 * Resource shell's `ActionMenu` awaits a non-deferred action's `run` with no
 * catch of its own - every OTHER action self-handles its errors).
 */
import { render } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import type { CloseReason } from '@/types/omnichannel';

import { WorkspaceCloseReasonsTab } from './workspace-close-reasons-tab';

const { toastErrorMock } = vi.hoisted(() => ({ toastErrorMock: vi.fn() }));
vi.mock('@/lib/toast', () => ({
  toast: { error: toastErrorMock, success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: () => true }) }));

const { updateMock, useCloseReasonsMock } = vi.hoisted(() => ({
  updateMock: vi.fn(),
  useCloseReasonsMock: vi.fn(),
}));
vi.mock('@/hooks/use-close-reasons', () => ({ useCloseReasons: useCloseReasonsMock }));

const { onSetActiveCapture } = vi.hoisted(() => ({ onSetActiveCapture: { current: null as unknown } }));
vi.mock('./use-close-reason-list', () => ({
  useCloseReasonList: (params: { onSetActive: (reason: CloseReason, isActive: boolean) => void }) => {
    onSetActiveCapture.current = params.onSetActive;
    return { config: { columns: [], fetcher: async () => ({ data: [], total: 0 }) } };
  },
}));

vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="close-reasons-list" />,
}));

vi.mock('./close-reason-dialog', () => ({
  CloseReasonDialog: () => null,
}));

function reason(over: Partial<CloseReason> = {}): CloseReason {
  return {
    id: 'cr-1', workspaceId: 'wsp-001', name: 'General Inquiry', sortOrder: 0, isActive: true, usesCount: 0,
    createdAt: '2026-01-01T00:00:00Z', ...over,
  };
}

beforeEach(() => {
  updateMock.mockReset();
  toastErrorMock.mockReset();
  onSetActiveCapture.current = null;
  useCloseReasonsMock.mockReturnValue({
    reasons: [reason()],
    create: vi.fn(),
    update: updateMock,
    refresh: vi.fn(),
  });
});

describe('WorkspaceCloseReasonsTab - Deactivate/Activate error handling (F6)', () => {
  it('toasts an error when update() rejects (e.g. a 409/500)', async () => {
    updateMock.mockRejectedValue(new ApiError('Reason no longer exists.', 404));
    render(<WorkspaceCloseReasonsTab workspaceId="wsp-001" creating={false} />);

    const onSetActive = onSetActiveCapture.current as (r: CloseReason, isActive: boolean) => void;
    expect(onSetActive).toBeInstanceOf(Function);

    await act(async () => {
      onSetActive(reason(), false);
      // let the async try/catch settle
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(updateMock).toHaveBeenCalledWith('cr-1', { isActive: false });
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    expect(toastErrorMock.mock.calls[0][0]).toContain('Reason no longer exists.');
  });

  it('does not toast when update() succeeds', async () => {
    updateMock.mockResolvedValue(reason({ isActive: false }));
    render(<WorkspaceCloseReasonsTab workspaceId="wsp-001" creating={false} />);

    const onSetActive = onSetActiveCapture.current as (r: CloseReason, isActive: boolean) => void;
    await act(async () => {
      onSetActive(reason(), false);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(toastErrorMock).not.toHaveBeenCalled();
  });
});

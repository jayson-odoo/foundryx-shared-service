/** AC-IVE-26/31/48 - close-reasons row actions: Delete only while usesCount
 *  === 0, Deactivate/Activate otherwise (D-A3-13). */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { CloseReason } from '@/types/omnichannel';
import { useCloseReasonList } from './use-close-reason-list';

// useDatetime() reads the session tz preference - no preference here, so
// formatters fall back to the runner's browser tz (same convention as
// conversation-drawer.test.tsx).
vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

function reason(over: Partial<CloseReason>): CloseReason {
  return {
    id: 'cr-1', workspaceId: 'wsp-001', name: 'General Inquiry', sortOrder: 0, isActive: true, usesCount: 0,
    createdAt: '2026-01-01T00:00:00Z', ...over,
  };
}

function actionsFor(reasons: CloseReason[]) {
  const { result } = renderHook(() =>
    useCloseReasonList({ reasons, canManage: true, onEdit: vi.fn(), onDelete: vi.fn(), onSetActive: vi.fn(), onAdd: vi.fn() }),
  );
  return result.current.config.actions ?? [];
}

describe('useCloseReasonList row actions', () => {
  it('an unused, active reason offers Delete and Deactivate, not Activate', () => {
    const row = reason({ usesCount: 0, isActive: true });
    const actions = actionsFor([row]);
    const visible = (id: string) => actions.find((a) => a.id === id)?.isVisible?.([row]) ?? false;
    expect(visible('delete')).toBe(true);
    expect(visible('deactivate')).toBe(true);
    expect(visible('activate')).toBe(false);
  });

  it('a USED reason (usesCount > 0) hides Delete - offers Deactivate instead (D-A3-13)', () => {
    const row = reason({ usesCount: 3, isActive: true });
    const actions = actionsFor([row]);
    const visible = (id: string) => actions.find((a) => a.id === id)?.isVisible?.([row]) ?? false;
    expect(visible('delete')).toBe(false);
    expect(visible('deactivate')).toBe(true);
  });

  it('an inactive reason offers Activate, not Deactivate', () => {
    const row = reason({ usesCount: 2, isActive: false });
    const actions = actionsFor([row]);
    const visible = (id: string) => actions.find((a) => a.id === id)?.isVisible?.([row]) ?? false;
    expect(visible('activate')).toBe(true);
    expect(visible('deactivate')).toBe(false);
  });

  it('hides the create action entirely when canManage is false', () => {
    const { result } = renderHook(() =>
      useCloseReasonList({
        reasons: [], canManage: false, onEdit: vi.fn(), onDelete: vi.fn(), onSetActive: vi.fn(), onAdd: vi.fn(),
      }),
    );
    expect(result.current.config.onCreate).toBeUndefined();
  });
});

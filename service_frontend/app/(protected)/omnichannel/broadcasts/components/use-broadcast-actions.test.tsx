/**
 * Broadcast action registry (plan 29 S4, AC-BRD-11/12) - one registry
 * serves the list row `…` menu, the bulk toolbar and the form `…` menu.
 * Covers the status-gated `isVisible` predicates (Edit/Delete = Draft only,
 * Send = Draft|Scheduled, Cancel = Scheduled|Sending), the `broadcasts.
 * manage`/`broadcasts.send` permission tags `useCan()` reads, and the typed
 * 409-reason -> friendly-copy mapping (AC-BRD-11's real backend conflicts).
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { Broadcast, BroadcastStatus } from '@/types/omnichannel';
import { useBroadcastActions } from './use-broadcast-actions';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const cancelMock = vi.fn();
const duplicateMock = vi.fn();
const sendMock = vi.fn();
const removeMock = vi.fn();
vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    cancel: (...args: unknown[]) => cancelMock(...args),
    duplicate: (...args: unknown[]) => duplicateMock(...args),
    send: (...args: unknown[]) => sendMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
  },
}));

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function broadcast(status: BroadcastStatus, overrides: Partial<Broadcast> = {}): Broadcast {
  return {
    id: 'bcst-1',
    workspaceId: 'wsp-1',
    name: 'Test broadcast',
    labels: [],
    channelId: 'chn-1',
    channelName: 'Demo',
    audience: { kind: 'contacts', contactIds: ['cnt-1'] },
    templateId: 'tpl-1',
    templateName: 'booking_update',
    templateLanguage: 'en_US',
    bindings: { header: [], body: [], buttons: [] },
    status,
    statusLabel: status,
    scheduledAt: null,
    startedAt: null,
    finishedAt: null,
    counts: { total: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 },
    jobId: null,
    error: null,
    createdByUserId: 'usr-1',
    createdByName: 'You',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function actionsFor(workspaceId = 'wsp-1') {
  const { result } = renderHook(() => useBroadcastActions(workspaceId));
  return result.current;
}

const find = (actions: ReturnType<typeof actionsFor>, id: string) => actions.find((a) => a.id === id)!;

describe('useBroadcastActions - status-gated visibility', () => {
  it('Edit and Delete are visible ONLY for a Draft broadcast', () => {
    const actions = actionsFor();
    for (const status of ['DRAFT', 'SCHEDULED', 'SENDING', 'SENT', 'CANCELLED', 'FAILED'] as BroadcastStatus[]) {
      const rows = [broadcast(status)];
      const expected = status === 'DRAFT';
      expect(find(actions, 'edit').isVisible!(rows)).toBe(expected);
      expect(find(actions, 'delete').isVisible!(rows)).toBe(expected);
    }
  });

  it('Send now is visible for Draft or Scheduled only', () => {
    const actions = actionsFor();
    expect(find(actions, 'send').isVisible!([broadcast('DRAFT')])).toBe(true);
    expect(find(actions, 'send').isVisible!([broadcast('SCHEDULED')])).toBe(true);
    expect(find(actions, 'send').isVisible!([broadcast('SENDING')])).toBe(false);
    expect(find(actions, 'send').isVisible!([broadcast('SENT')])).toBe(false);
  });

  it('Cancel is visible for Scheduled or Sending only', () => {
    const actions = actionsFor();
    expect(find(actions, 'cancel').isVisible!([broadcast('SCHEDULED')])).toBe(true);
    expect(find(actions, 'cancel').isVisible!([broadcast('SENDING')])).toBe(true);
    expect(find(actions, 'cancel').isVisible!([broadcast('DRAFT')])).toBe(false);
    expect(find(actions, 'cancel').isVisible!([broadcast('SENT')])).toBe(false);
    expect(find(actions, 'cancel').isVisible!([broadcast('CANCELLED')])).toBe(false);
  });

  it('a MIXED bulk selection requires every row to satisfy the predicate', () => {
    const actions = actionsFor();
    expect(find(actions, 'send').isVisible!([broadcast('DRAFT'), broadcast('SENT')])).toBe(false);
    expect(find(actions, 'cancel').isVisible!([broadcast('SCHEDULED'), broadcast('SENDING')])).toBe(true);
  });

  it('Duplicate is visible for exactly one selected row, any status', () => {
    const actions = actionsFor();
    expect(find(actions, 'duplicate').isVisible!([broadcast('SENT')])).toBe(true);
    expect(find(actions, 'duplicate').isVisible!([broadcast('SENT'), broadcast('DRAFT')])).toBe(false);
    expect(find(actions, 'duplicate').isVisible!([])).toBe(false);
  });
});

describe('useBroadcastActions - permission gating (AC-BRD-12)', () => {
  it('Send/Cancel are gated broadcasts.send; Edit/Duplicate/Delete are gated broadcasts.manage', () => {
    const actions = actionsFor();
    expect(find(actions, 'send').permission).toBe('broadcasts.send');
    expect(find(actions, 'cancel').permission).toBe('broadcasts.send');
    expect(find(actions, 'edit').permission).toBe('broadcasts.manage');
    expect(find(actions, 'duplicate').permission).toBe('broadcasts.manage');
    expect(find(actions, 'delete').permission).toBe('broadcasts.manage');
  });
});

describe('useBroadcastActions - Delete is a deferred action (review round 1, S1)', () => {
  it('Delete has no immediate `run` - it registers the grace-window `broadcasts.delete` handler', () => {
    const actions = actionsFor();
    const del = find(actions, 'delete');
    expect(del.deferred).toEqual({ actionKey: 'broadcasts.delete', entityType: 'broadcast' });
    expect(del.run).toBeUndefined();
    expect(del.confirm).toBeUndefined();
  });
});

describe('useBroadcastActions - run() against the real service', () => {
  it('cancel() calls broadcastService.cancel and reloads on success', async () => {
    cancelMock.mockResolvedValueOnce(broadcast('CANCELLED'));
    const actions = actionsFor();
    const reload = vi.fn();
    await find(actions, 'cancel').run!([broadcast('SENDING')], { reload });
    expect(cancelMock).toHaveBeenCalledWith('wsp-1', 'bcst-1');
    expect(reload).toHaveBeenCalled();
  });

  it('a typed 409 (broadcast_not_cancellable) is surfaced as friendly copy, not "Conflict"', async () => {
    const { toast } = await import('@/lib/toast');
    cancelMock.mockRejectedValueOnce(new ApiError('Conflict', 409, null, { reason: 'broadcast_not_cancellable' }));
    const actions = actionsFor();
    const reload = vi.fn();
    await find(actions, 'cancel').run!([broadcast('SENDING')], { reload });
    expect(toast.error).toHaveBeenCalledWith('This broadcast can no longer be cancelled.');
    expect(reload).not.toHaveBeenCalled();
  });

  it('duplicate() calls broadcastService.duplicate and reloads on success', async () => {
    duplicateMock.mockResolvedValueOnce(broadcast('DRAFT', { id: 'bcst-2', name: 'Test broadcast (copy)' }));
    const actions = actionsFor();
    const reload = vi.fn();
    await find(actions, 'duplicate').run!([broadcast('SENT')], { reload });
    expect(duplicateMock).toHaveBeenCalledWith('wsp-1', 'bcst-1');
    expect(reload).toHaveBeenCalled();
  });
});

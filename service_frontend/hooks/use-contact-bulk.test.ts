/**
 * Bulk contact mutations (D-A2-5, AC-CTM-09/46) - `reportBulkResult` is the
 * ONE partial-failure rendering every bulk dialog (Assign/Tags/Lifecycle)
 * feeds into: full success -> one toast; a mix -> a warning naming the
 * failure count AND per-record reasons (never a bare "something went
 * wrong"); total failure -> an error toast. `useContactBulk` wires each verb
 * to the matching `contactService` call, workspace-scoped.
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from '@/lib/toast';
import type { BulkResult } from '@/types/omnichannel';

vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const bulkAssign = vi.fn();
const bulkTags = vi.fn();
const bulkLifecycle = vi.fn();
vi.mock('@/services/contact-service', () => ({
  contactService: {
    bulkAssign: (...args: unknown[]) => bulkAssign(...args),
    bulkTags: (...args: unknown[]) => bulkTags(...args),
    bulkLifecycle: (...args: unknown[]) => bulkLifecycle(...args),
  },
}));

import { reportBulkResult, useContactBulk } from './use-contact-bulk';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('reportBulkResult', () => {
  it('renders a plain success toast when nothing failed', () => {
    const result: BulkResult = { ok: ['a', 'b'], failed: [] };
    reportBulkResult(result, 'assigned');
    expect(toast.success).toHaveBeenCalledWith('2 contacts assigned.');
    expect(toast.warning).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('singularizes the count', () => {
    reportBulkResult({ ok: ['a'], failed: [] }, 'tagged');
    expect(toast.success).toHaveBeenCalledWith('1 contact tagged.');
  });

  it('renders a warning naming BOTH the split AND every per-record reason on a partial failure', () => {
    const result: BulkResult = {
      ok: ['cnt-1'],
      failed: [{ id: 'cnt-2', error: 'No move from Won.' }],
    };
    reportBulkResult(result, 'moved');
    expect(toast.warning).toHaveBeenCalledWith(
      '1 moved, 1 failed.',
      expect.objectContaining({ description: 'cnt-2: No move from Won.' }),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('renders an error (never a bare "something went wrong") when every record failed', () => {
    const result: BulkResult = {
      ok: [],
      failed: [
        { id: 'cnt-1', error: 'Contact not found.' },
        { id: 'cnt-2', error: 'Contact not found.' },
      ],
    };
    reportBulkResult(result, 'untagged');
    expect(toast.error).toHaveBeenCalledWith(
      'Could not update 2 contacts.',
      expect.objectContaining({ description: 'cnt-1: Contact not found.\ncnt-2: Contact not found.' }),
    );
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.warning).not.toHaveBeenCalled();
  });
});

describe('useContactBulk', () => {
  it('routes assign/tags/lifecycle to the matching workspace-scoped service call', async () => {
    bulkAssign.mockResolvedValue({ ok: ['cnt-1'], failed: [] });
    bulkTags.mockResolvedValue({ ok: ['cnt-1'], failed: [] });
    bulkLifecycle.mockResolvedValue({ ok: ['cnt-1'], failed: [] });

    const { result } = renderHook(() => useContactBulk('wsp-1'));

    await act(async () => {
      await result.current.assign(['cnt-1'], 'user-1');
    });
    expect(bulkAssign).toHaveBeenCalledWith('wsp-1', { ids: ['cnt-1'], assigneeUserId: 'user-1' });

    await act(async () => {
      await result.current.tags(['cnt-1'], 'add', ['tag-1']);
    });
    expect(bulkTags).toHaveBeenCalledWith('wsp-1', { ids: ['cnt-1'], mode: 'add', tagIds: ['tag-1'] });

    await act(async () => {
      await result.current.lifecycle(['cnt-1'], 'st-2');
    });
    expect(bulkLifecycle).toHaveBeenCalledWith('wsp-1', { ids: ['cnt-1'], toStatusId: 'st-2' });
  });

  it('throws (never silently no-ops) when no workspace is resolved yet', async () => {
    const { result } = renderHook(() => useContactBulk(null));
    await expect(result.current.assign(['cnt-1'], null)).rejects.toThrow('No workspace selected.');
  });
});

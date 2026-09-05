/**
 * Contact action registry (D-A2-5, AC-CTM-09/46 permission gating) - every
 * action is gated `contacts.manage` (ActionMenu/BulkActions read
 * `ResourceAction.permission` via `useCan` - UX only, the backend re-checks),
 * surfaces on both row + bulk, and "Remove tags" only shows for a selection
 * that actually has at least one tag (foolproof-UI - never offer an action
 * guaranteed to no-op).
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ContactListItem } from '@/types/omnichannel';
import { useContactActions } from './use-contact-actions';

function row(overrides: Partial<ContactListItem> = {}): ContactListItem {
  return {
    id: 'cnt-1',
    tenantId: 't1',
    workspaceId: 'wsp-1',
    name: 'Ada Lovelace',
    firstName: 'Ada',
    lastName: 'Lovelace',
    phone: '+60123456789',
    email: null,
    language: null,
    countryCode: null,
    avatarUrl: null,
    assignedUserId: null,
    assignedUserName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: null,
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: {},
    tags: [],
    lifecycle: null,
    createdAt: '2026-01-01T00:00:00Z',
    channels: [],
    ...overrides,
  };
}

describe('useContactActions', () => {
  it('gates every action on contacts.manage, surfaced on row AND bulk', () => {
    const { result } = renderHook(() =>
      useContactActions({
        onBulkAssign: vi.fn(),
        onAddTags: vi.fn(),
        onRemoveTags: vi.fn(),
        onMoveLifecycle: vi.fn(),
      }),
    );
    const actions = result.current;
    expect(actions.map((a) => a.id)).toEqual(['bulk-assign', 'add-tags', 'remove-tags', 'move-lifecycle']);
    for (const action of actions) {
      expect(action.permission).toBe('contacts.manage');
      expect(action.surfaces).toEqual({ row: true, bulk: true });
    }
  });

  it('hides "Remove tags" for a selection with zero tags, shows it once any row carries a tag', () => {
    const { result } = renderHook(() =>
      useContactActions({
        onBulkAssign: vi.fn(),
        onAddTags: vi.fn(),
        onRemoveTags: vi.fn(),
        onMoveLifecycle: vi.fn(),
      }),
    );
    const removeTags = result.current.find((a) => a.id === 'remove-tags')!;
    expect(removeTags.isVisible?.([row()])).toBe(false);
    expect(
      removeTags.isVisible?.([row({ tags: [{ id: 'tag-1', name: 'VIP', emoji: null, color: '#000' }] })]),
    ).toBe(true);
  });

  it('runs the matching callback with the selected rows + reload', () => {
    const onMoveLifecycle = vi.fn();
    const { result } = renderHook(() =>
      useContactActions({
        onBulkAssign: vi.fn(),
        onAddTags: vi.fn(),
        onRemoveTags: vi.fn(),
        onMoveLifecycle,
      }),
    );
    const reload = vi.fn();
    const rows = [row()];
    result.current.find((a) => a.id === 'move-lifecycle')!.run(rows, { reload, ctx: undefined, index: 0 });
    expect(onMoveLifecycle).toHaveBeenCalledWith(rows, reload);
  });
});

/**
 * Round-3 codex triage F4: URL-restoration lifecycle for the inbox view
 * rail. `restoredRef` used to be "done forever" for the hook's whole
 * lifetime - a workspace switch (same mounted component, new stages/views)
 * never re-attempted restoration, and an unknown/stale rail key was never
 * normalized (silent no-op, URL left pointing at a dead key).
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_FILTERS, type ConversationFilters } from '@/hooks/use-conversations';
import type { InboxView } from '@/types/omnichannel';

import { useInboxRailSelection } from './use-inbox-rail-selection';

function view(over: Partial<InboxView> = {}): InboxView {
  return {
    id: 'view-1',
    workspaceId: 'wsp-a',
    name: 'My view',
    ownerUserId: 'usr-1',
    ownerName: 'Owner',
    isShared: false,
    filter: {},
    sortOrder: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

function setUrl(key: string | null) {
  window.history.replaceState(null, '', key ? `/?view=${key}` : '/');
}

beforeEach(() => setUrl(null));

describe('useInboxRailSelection - URL restoration', () => {
  it('restores a saved-view key once views load', () => {
    setUrl('view-1');
    const setFilters = vi.fn();
    const views = [view({ id: 'view-1' })];
    renderHook(
      ({ filters }: { filters: ConversationFilters }) =>
        useInboxRailSelection(filters, setFilters, [], views, 'wsp-a'),
      { initialProps: { filters: DEFAULT_FILTERS } },
    );
    expect(setFilters).toHaveBeenCalledWith(expect.objectContaining({ viewId: 'view-1' }));
  });

  // F4 - a workspace switch (same hook instance) must re-attempt restoration
  // against the NEW workspace's own views, not silently keep whatever the
  // FIRST workspace resolved (`restoredRef` used to be "done forever" the
  // instant the FIRST workspace's restoration succeeded).
  it('re-attempts restoration when the workspace changes', () => {
    setUrl('view-1');
    const setFilters = vi.fn();
    const { rerender } = renderHook(
      ({ filters, views, workspaceId }: { filters: ConversationFilters; views: InboxView[]; workspaceId: string }) =>
        useInboxRailSelection(filters, setFilters, [], views, workspaceId),
      {
        initialProps: {
          filters: DEFAULT_FILTERS,
          views: [view({ id: 'view-1', workspaceId: 'wsp-a', name: 'Workspace A view' })],
          workspaceId: 'wsp-a',
        },
      },
    );
    // First workspace's own view restores - `restoredRef` is now "done".
    expect(setFilters).toHaveBeenCalledTimes(1);
    expect(setFilters).toHaveBeenNthCalledWith(1, expect.objectContaining({ viewId: 'view-1' }));

    // Switch to a DIFFERENT workspace whose OWN row happens to carry the SAME
    // id (URL key unchanged) but different content - the restoration must
    // run AGAIN for this workspace (a second `setFilters` call), not stay
    // permanently "done" from the first workspace's success.
    act(() => {
      rerender({
        filters: DEFAULT_FILTERS,
        views: [view({ id: 'view-1', workspaceId: 'wsp-b', name: 'Workspace B view' })],
        workspaceId: 'wsp-b',
      });
    });
    expect(setFilters).toHaveBeenCalledTimes(2);
    expect(setFilters).toHaveBeenNthCalledWith(2, expect.objectContaining({ viewId: 'view-1' }));
  });

  // F4 - an unknown/deleted view id normalizes to All (URL + filters), not a
  // silent no-op that strands the URL on a dead key.
  it('normalizes an unknown saved-view key to All', () => {
    setUrl('does-not-exist');
    const setFilters = vi.fn();
    renderHook(
      ({ filters }: { filters: ConversationFilters }) =>
        useInboxRailSelection(filters, setFilters, [], [view({ id: 'view-1' })], 'wsp-a'),
      { initialProps: { filters: DEFAULT_FILTERS } },
    );
    expect(setFilters).toHaveBeenCalledWith(
      expect.objectContaining({ assignee: 'all', viewId: null }),
    );
    expect(new URLSearchParams(window.location.search).get('view')).toBe('all');
  });

  it('normalizes an unknown lifecycle key to All', () => {
    setUrl('lifecycle:does-not-exist');
    const setFilters = vi.fn();
    renderHook(
      ({ filters }: { filters: ConversationFilters }) =>
        useInboxRailSelection(filters, setFilters, [{ id: 'stg-1', label: 'New', color: null }], [], 'wsp-a'),
      { initialProps: { filters: DEFAULT_FILTERS } },
    );
    expect(setFilters).toHaveBeenCalledWith(
      expect.objectContaining({ assignee: 'all', viewId: null }),
    );
    expect(new URLSearchParams(window.location.search).get('view')).toBe('all');
  });

  // Plan 28 (roadmap A8) - a Team Inbox scope (restored independently by
  // `useConversations` from `?team=`/`?assignee=`) must NOT be clobbered by
  // a STALE `?view=` param left over from a rail selection made before the
  // team was picked (`select()` clears `?view=` when picking a team, but an
  // old tab/bookmark could still carry both params together).
  it('never restores a stale ?view= when a team scope is already active', () => {
    setUrl('me'); // stale - would normally restore assignee='me'
    const setFilters = vi.fn();
    const teamFilters: ConversationFilters = { ...DEFAULT_FILTERS, teamId: 'team-1', assignee: 'all' };
    renderHook(
      ({ filters }: { filters: ConversationFilters }) =>
        useInboxRailSelection(filters, setFilters, [], [], 'wsp-a'),
      { initialProps: { filters: teamFilters } },
    );
    expect(setFilters).not.toHaveBeenCalled();
  });
});

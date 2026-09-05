import { describe, expect, it } from 'vitest';

import type { InboxView } from '@/types/omnichannel';

import {
  buildRailEntries,
  expandViewFilter,
  parseRailKey,
  railKeyForStage,
  railSelectionPatch,
} from './inbox-rail-entries';

function view(over: Partial<InboxView> = {}): InboxView {
  return {
    id: 'view-1',
    workspaceId: 'wsp-001',
    name: 'My view',
    ownerUserId: 'usr-demo',
    ownerName: 'Demo User',
    isShared: false,
    filter: {},
    sortOrder: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('buildRailEntries', () => {
  it('always includes All / Mine / Unassigned first', () => {
    const entries = buildRailEntries([], []);
    expect(entries.slice(0, 3)).toEqual([
      { kind: 'default', key: 'all', label: 'All' },
      { kind: 'default', key: 'me', label: 'Mine' },
      { kind: 'default', key: 'unassigned', label: 'Unassigned' },
    ]);
  });

  it('adds one entry per lifecycle stage, then saved views in sortOrder', () => {
    const entries = buildRailEntries(
      [{ id: 'stg-1', label: '🆕 New Lead', color: '#3B82F6' }],
      [view({ id: 'v2', sortOrder: 1, name: 'Second' }), view({ id: 'v1', sortOrder: 0, name: 'First' })],
    );
    expect(entries).toContainEqual({
      kind: 'lifecycle', key: 'lifecycle:stg-1', stageId: 'stg-1', label: '🆕 New Lead', color: '#3B82F6',
    });
    const viewEntries = entries.filter((e) => e.kind === 'view');
    expect(viewEntries.map((e) => (e as { label: string }).label)).toEqual(['First', 'Second']);
  });
});

describe('railSelectionPatch', () => {
  it('a default entry resets lifecycle/view selection', () => {
    expect(railSelectionPatch({ kind: 'default', key: 'me', label: 'Mine' })).toEqual({
      assignee: 'me', lifecycleStageIds: [], viewId: null,
    });
  });

  it('a lifecycle entry filters to that ONE stage and resets assignee/view', () => {
    expect(
      railSelectionPatch({ kind: 'lifecycle', key: railKeyForStage('stg-1'), stageId: 'stg-1', label: 'X', color: null }),
    ).toEqual({ assignee: 'all', lifecycleStageIds: ['stg-1'], viewId: null });
  });
});

describe('expandViewFilter', () => {
  it('expands the stored filter into the list-query shape (AC-IVE-17)', () => {
    const v = view({
      filter: {
        statuses: ['OPEN'],
        assignee: 'me',
        lifecycleStageIds: ['stg-1'],
        tagIds: ['tag-1'],
        unreplied: true,
        sort: 'longest_waiting',
      },
    });
    expect(expandViewFilter(v)).toEqual({
      assignee: 'me',
      status: 'OPEN',
      priority: 'ALL',
      lifecycleStageIds: ['stg-1'],
      tagIds: ['tag-1'],
      channelIds: [],
      unreplied: true,
      sort: 'longest_waiting',
      viewId: v.id,
    });
  });

  it('collapses a multi-status filter to ALL (today\'s list route is single-value)', () => {
    const v = view({ filter: { statuses: ['OPEN', 'SNOOZED'] } });
    expect(expandViewFilter(v).status).toBe('ALL');
  });

  it('collapses assignee "user" (specific ids) to "all" (no per-user list param yet)', () => {
    const v = view({ filter: { assignee: 'user', assigneeUserIds: ['usr-x'] } });
    expect(expandViewFilter(v).assignee).toBe('all');
  });
});

describe('parseRailKey', () => {
  it('recognizes the three reserved default keys', () => {
    expect(parseRailKey('all')).toEqual({ kind: 'default', value: 'all' });
    expect(parseRailKey('me')).toEqual({ kind: 'default', value: 'me' });
    expect(parseRailKey('unassigned')).toEqual({ kind: 'default', value: 'unassigned' });
  });

  it('recognizes a lifecycle key', () => {
    expect(parseRailKey('lifecycle:stg-1')).toEqual({ kind: 'lifecycle', value: 'stg-1' });
  });

  it('treats anything else as a saved-view id', () => {
    expect(parseRailKey('view-42')).toEqual({ kind: 'view', value: 'view-42' });
  });
});

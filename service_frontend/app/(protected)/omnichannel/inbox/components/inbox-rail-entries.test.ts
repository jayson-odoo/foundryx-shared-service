import { describe, expect, it } from 'vitest';

import type { InboxView } from '@/types/omnichannel';

import {
  buildRailEntries,
  expandViewFilter,
  parseRailKey,
  railKeyForStage,
  railKeyForTeam,
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

  // Plan 28 (roadmap A8, D-A8-4) - each team contributes a main entry + a
  // nested Unassigned entry, "mine" before "other" (My teams before All teams).
  it('adds a main + Unassigned entry per team, scoped mine-then-other', () => {
    const entries = buildRailEntries([], [], {
      mine: [{ id: 'team-1', name: 'Sales' }],
      other: [{ id: 'team-2', name: 'Support' }],
    });
    const teamEntries = entries.filter((e) => e.kind === 'team');
    expect(teamEntries).toEqual([
      { kind: 'team', key: 'team:team-1', teamId: 'team-1', unassigned: false, label: 'Sales', scope: 'mine' },
      { kind: 'team', key: 'team:team-1:unassigned', teamId: 'team-1', unassigned: true, label: 'Sales - Unassigned', scope: 'mine' },
      { kind: 'team', key: 'team:team-2', teamId: 'team-2', unassigned: false, label: 'Support', scope: 'other' },
      { kind: 'team', key: 'team:team-2:unassigned', teamId: 'team-2', unassigned: true, label: 'Support - Unassigned', scope: 'other' },
    ]);
  });
});

describe('railSelectionPatch', () => {
  it('a default entry resets lifecycle/view selection', () => {
    expect(railSelectionPatch({ kind: 'default', key: 'me', label: 'Mine' })).toEqual({
      assignee: 'me', lifecycleStageIds: [], tagIds: [], channelIds: [], viewId: null, teamId: null,
    });
  });

  it('a lifecycle entry filters to that ONE stage and resets assignee/view', () => {
    expect(
      railSelectionPatch({ kind: 'lifecycle', key: railKeyForStage('stg-1'), stageId: 'stg-1', label: 'X', color: null }),
    ).toEqual({ assignee: 'all', lifecycleStageIds: ['stg-1'], tagIds: [], channelIds: [], viewId: null, teamId: null });
  });

  // Plan 28 - a team entry scopes to that team (+ Unassigned when nested) and
  // resets the other rail-driven dimensions (lifecycle/view); a default,
  // lifecycle, or view entry likewise clears `teamId` (never a hidden,
  // un-clearable team scope left over after picking a different rail entry).
  it('a team entry scopes to that team and clears lifecycle/view', () => {
    expect(
      railSelectionPatch({ kind: 'team', key: railKeyForTeam('team-1', false), teamId: 'team-1', unassigned: false, label: 'Sales', scope: 'mine' }),
    ).toEqual({ assignee: 'all', lifecycleStageIds: [], tagIds: [], channelIds: [], viewId: null, teamId: 'team-1' });
  });

  it('a team\'s nested Unassigned entry scopes to that team AND assignee=unassigned', () => {
    expect(
      railSelectionPatch({ kind: 'team', key: railKeyForTeam('team-1', true), teamId: 'team-1', unassigned: true, label: 'Sales - Unassigned', scope: 'mine' }),
    ).toEqual({ assignee: 'unassigned', lifecycleStageIds: [], tagIds: [], channelIds: [], viewId: null, teamId: 'team-1' });
  });

  it('a view entry clears a previously-active team scope', () => {
    expect(railSelectionPatch({ kind: 'view', key: 'view-1', viewId: 'view-1', label: 'X', isShared: false }).teamId).toBeNull();
  });

  // F1 (round-3 codex triage): tagIds/channelIds are VIEW-ONLY dimensions -
  // leaving a saved view for any rail entry must clear them, or the view's
  // narrowing keeps silently applying with no UI left to show/clear it.
  it('a default entry clears a previously-active view\'s tag/channel filters', () => {
    const patch = railSelectionPatch({ kind: 'default', key: 'all', label: 'All' });
    expect(patch.tagIds).toEqual([]);
    expect(patch.channelIds).toEqual([]);
  });

  it('a lifecycle entry clears a previously-active view\'s tag/channel filters', () => {
    const patch = railSelectionPatch({
      kind: 'lifecycle', key: railKeyForStage('stg-1'), stageId: 'stg-1', label: 'X', color: null,
    });
    expect(patch.tagIds).toEqual([]);
    expect(patch.channelIds).toEqual([]);
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
      statusExplicit: false,
      priority: 'ALL',
      lifecycleStageIds: ['stg-1'],
      tagIds: ['tag-1'],
      channelIds: [],
      unreplied: true,
      sort: 'longest_waiting',
      viewId: v.id,
      teamId: null,
    });
  });

  it('collapses a multi-status filter to ALL (today\'s list route is single-value)', () => {
    const v = view({ filter: { statuses: ['OPEN', 'SNOOZED'] } });
    expect(expandViewFilter(v).status).toBe('ALL');
  });

  // F2 (round-3 codex triage) - the collapse above must NEVER be sent to the
  // server as an explicit override (it would clear the view's real
  // multi-status filter) - `statusExplicit` stays false for every expansion,
  // single-status or multi-status alike.
  it('always marks the expanded status as NOT explicit (never a user override)', () => {
    expect(expandViewFilter(view({ filter: { statuses: ['OPEN'] } })).statusExplicit).toBe(false);
    expect(expandViewFilter(view({ filter: { statuses: ['OPEN', 'SNOOZED'] } })).statusExplicit).toBe(false);
    expect(expandViewFilter(view({ filter: {} })).statusExplicit).toBe(false);
  });

  it('collapses assignee "user" (specific ids) to "all" (no per-user list param yet)', () => {
    const v = view({ filter: { assignee: 'user', assigneeUserIds: ['usr-x'] } });
    expect(expandViewFilter(v).assignee).toBe('all');
  });

  it('AC-TEM-46: restores the saved team scope from filter.teamIds (first id)', () => {
    const v = view({ filter: { teamIds: ['team-1'] } });
    expect(expandViewFilter(v).teamId).toBe('team-1');
  });

  it('AC-TEM-46: a view saved before teamIds existed has no team scope', () => {
    const v = view({ filter: {} });
    expect(expandViewFilter(v).teamId).toBeNull();
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

/**
 * Pure helpers for the inbox view rail (plan 27, AC-IVE-20): the entry list
 * (All / Mine / Unassigned, one per lifecycle stage, one per saved view) and
 * the filter patch + URL key each entry maps to. Kept side-effect free so
 * vitest can cover the mapping without mounting the rail component.
 *
 * Frontend scope note: `InboxViewFilter.statuses` (an array) and
 * `assignee: 'user'` (specific assignee ids) are richer than the inbox's
 * current filter UI (`status` is single-value, `assignee` has no per-user
 * option - there is no picker to author such a view from this surface). A
 * saved view carrying either collapses to the closest single-value
 * equivalent here; the backend list route (`GET /omnichannel/contacts`)
 * fully supports both, so a view authored another way still filters
 * correctly server-side even though this rail can't build one.
 */
import type { ConversationFilters } from '@/hooks/use-conversations';
import type { InboxView, ThreadStatus } from '@/types/omnichannel';

export interface RailStage {
  id: string;
  label: string;
  color: string | null;
}

export type InboxRailEntry =
  // `key` mirrors `ConversationFilters.assignee` exactly ('me', not 'mine') so
  // there is no separate translation table between the rail and the filters.
  | { kind: 'default'; key: 'all' | 'me' | 'unassigned'; label: string }
  | { kind: 'lifecycle'; key: string; stageId: string; label: string; color: string | null }
  | { kind: 'view'; key: string; viewId: string; label: string; isShared: boolean };

const LIFECYCLE_PREFIX = 'lifecycle:';

export function railKeyForStage(stageId: string): string {
  return `${LIFECYCLE_PREFIX}${stageId}`;
}
export function railKeyForView(viewId: string): string {
  return viewId;
}

export function buildRailEntries(stages: RailStage[], views: InboxView[]): InboxRailEntry[] {
  const defaults: InboxRailEntry[] = [
    { kind: 'default', key: 'all', label: 'All' },
    { kind: 'default', key: 'me', label: 'Mine' },
    { kind: 'default', key: 'unassigned', label: 'Unassigned' },
  ];
  const lifecycle: InboxRailEntry[] = stages.map((s) => ({
    kind: 'lifecycle',
    key: railKeyForStage(s.id),
    stageId: s.id,
    label: s.label,
    color: s.color,
  }));
  const savedViews: InboxRailEntry[] = [...views]
    .sort((a, b) => a.sortOrder - b.sortOrder)
    .map((v) => ({ kind: 'view', key: railKeyForView(v.id), viewId: v.id, label: v.name, isShared: v.isShared }));
  return [...defaults, ...lifecycle, ...savedViews];
}

function singleStatus(statuses: ThreadStatus[] | undefined): ThreadStatus | 'ALL' {
  if (!statuses || statuses.length !== 1) return 'ALL';
  return statuses[0];
}

/** The filter patch a rail entry applies - selecting ANY entry resets the
 *  other rail-driven dimensions (assignee/lifecycle/view are mutually
 *  exclusive), but leaves Show/Sort/Unreplied untouched EXCEPT when a saved
 *  view is chosen, which restores its own stored values (AC-IVE-17). */
export function railSelectionPatch(entry: InboxRailEntry): Partial<ConversationFilters> {
  switch (entry.kind) {
    case 'default':
      return { assignee: entry.key, lifecycleStageIds: [], viewId: null };
    case 'lifecycle':
      return { assignee: 'all', lifecycleStageIds: [entry.stageId], viewId: null };
    case 'view':
      return { viewId: entry.viewId };
  }
}

/** Expand a saved view's stored filter into the list's filter shape
 *  (AC-IVE-17 - explicit params sent alongside would override; the rail
 *  applies the view wholesale on selection). */
export function expandViewFilter(view: InboxView): Partial<ConversationFilters> {
  const f = view.filter;
  return {
    assignee: f.assignee === 'user' ? 'all' : (f.assignee ?? 'all'),
    status: singleStatus(f.statuses),
    priority: f.priority ?? 'ALL',
    lifecycleStageIds: f.lifecycleStageIds ?? [],
    tagIds: f.tagIds ?? [],
    channelIds: f.channelIds ?? [],
    unreplied: f.unreplied ?? false,
    sort: f.sort ?? 'newest',
    viewId: view.id,
  };
}

export function parseRailKey(key: string): { kind: 'default' | 'lifecycle' | 'view'; value: string } {
  if (key === 'all' || key === 'me' || key === 'unassigned') return { kind: 'default', value: key };
  if (key.startsWith(LIFECYCLE_PREFIX)) return { kind: 'lifecycle', value: key.slice(LIFECYCLE_PREFIX.length) };
  return { kind: 'view', value: key };
}

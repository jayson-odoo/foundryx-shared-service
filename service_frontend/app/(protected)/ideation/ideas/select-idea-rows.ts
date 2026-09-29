import type { Idea } from '@/types/ideation';
import type { ListQuery } from '@/types/resource';
import { evalGroup, type QueryAdapter } from '@/services/mock-query';

const net = (i: Idea): number => (i.upvotes ?? 0) - (i.downvotes ?? 0);
const time = (iso: string): number => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
};

/** Filter-field name -> value read off an idea (engine keys/labels only, no
 * hardcoded status union). */
const ADAPTER: QueryAdapter<Idea> = {
  getField: (i, field) => {
    switch (field) {
      case 'status':
        return i.status;
      case 'submitter':
        return i.submitterName;
      case 'channel':
        return i.source;
      case 'product':
        return i.productName;
      case 'votes':
        return net(i);
      case 'submitted':
        return i.createdAt;
      case 'problem':
        return i.title ?? i.problem;
      default:
        return undefined;
    }
  },
  searchFields: [],
};

/** Typed comparator per sortable column id (numbers for votes, dates for
 * submitted - never a string compare). */
function compareBy(id: string, a: Idea, b: Idea): number {
  switch (id) {
    case 'votes':
      return net(a) - net(b);
    case 'submitted':
      return time(a.createdAt) - time(b.createdAt);
    case 'problem':
      return (a.title ?? a.problem).localeCompare(b.title ?? b.problem);
    case 'submitter':
      return a.submitterName.localeCompare(b.submitterName);
    case 'channel':
      return String(a.source).localeCompare(String(b.source));
    case 'product':
      return a.productName.localeCompare(b.productName);
    case 'status':
      return (a.statusLabel ?? a.status).localeCompare(b.statusLabel ?? b.status);
    default:
      return 0;
  }
}

/** Default order: net votes desc, then upvotes desc, then newest first. */
function byNetVotes(a: Idea, b: Idea): number {
  return net(b) - net(a) || (b.upvotes ?? 0) - (a.upvotes ?? 0) || time(b.createdAt) - time(a.createdAt);
}

/**
 * The ONE pure view helper the list fetcher AND the record pager both run
 * (issue #94 / plan sprint-5/15) - so search, the Active|Archived view, the
 * filter builder and the sort can never drift between the grid and "prev/next".
 *
 * Active/Archived splits on the engine trait `statusIsArchived` (AC-94-60),
 * never a hardcoded status key. The shell's sort/filter are manual, so they are
 * applied here: no `sort` = net votes desc (AC-15-08); a chosen sort uses typed
 * comparators.
 */
export function selectIdeaRows(
  ideas: Idea[],
  query: Pick<ListQuery, 'search' | 'statusView' | 'filter' | 'sort'>,
): Idea[] {
  const archivedView = query.statusView === 'trashed';
  let rows = ideas.filter((r) => (archivedView ? Boolean(r.statusIsArchived) : !r.statusIsArchived));
  if (query.search) {
    const s = query.search.toLowerCase();
    rows = rows.filter(
      (r) =>
        r.problem.toLowerCase().includes(s) ||
        r.submitterName.toLowerCase().includes(s) ||
        r.productName.toLowerCase().includes(s),
    );
  }
  const filter = query.filter;
  if (filter && filter.rules.length) {
    rows = rows.filter((r) => evalGroup(r, filter, ADAPTER));
  }
  const sort = query.sort;
  if (sort) {
    const dir = sort.desc ? -1 : 1;
    return [...rows].sort((a, b) => dir * compareBy(sort.id, a, b) || byNetVotes(a, b));
  }
  return [...rows].sort(byNetVotes);
}

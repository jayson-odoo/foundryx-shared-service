import type { Idea } from '@/types/ideation';
import type { ListQuery } from '@/types/resource';

/**
 * The ONE pure view helper the list fetcher AND the record pager both run
 * (issue #94, ideation round 2, plan section 4.3/5) - so a search or the
 * Active|Archived view can never drift between the grid and "prev/next".
 *
 * Active/Archived splits on the engine trait `statusIsArchived` (AC-94-60),
 * never a hardcoded status key - a tenant that renamed a status still
 * archives correctly. Order is the SERVER's order (AC-94-47) - no client
 * `.sort()` by the raw `priority`.
 */
export function selectIdeaRows(ideas: Idea[], query: Pick<ListQuery, 'search' | 'statusView'>): Idea[] {
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
  return rows;
}

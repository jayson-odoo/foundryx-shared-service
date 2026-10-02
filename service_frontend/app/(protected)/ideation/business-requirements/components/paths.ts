export const BR_PATH = '/ideation/business-requirements';

export function brPath(id: string): string {
  return `${BR_PATH}/${id}`;
}

/** Form href preserving record-nav context (ctx + index), optionally edit mode
 * and an initial tab (e.g. `grill` - Promote-to-BR lands on the Grill tab).
 * `includeTest` (review fix S6, issue #90 W3) rides alongside `ctx`/`i`/`from`
 * the same way they do - a plain sibling URL param, carrying the LIST's own
 * "Show test requirements" toggle state so the record pager on the far side
 * re-runs the SAME lane the user was actually browsing, not a lane re-derived
 * from whichever record happens to be open (a real BR opened from a
 * test-inclusive list must page through that SAME mixed set, not silently
 * narrow to real-only). `resource-list.tsx`'s `buildListNav` only touches the
 * `ctx`/`i`/`from` keys, so this param survives that wrapping untouched. */
export function brFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean; tab?: string; includeTest?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.tab) params.set('tab', opts.tab);
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  if (opts?.includeTest) params.set('includeTest', '1');
  const qs = params.toString();
  return qs ? `${brPath(id)}?${qs}` : brPath(id);
}

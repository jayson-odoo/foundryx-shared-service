/** Route helpers for the Ideas feature - single source of truth for its URLs. */

export const ideasListPath = '/ideation/ideas';
export const ideaNewPath = `${ideasListPath}/new`;
export const ideaFormPath = (id: string) => `${ideasListPath}/${id}`;

/** Builds the query string shared by every idea form href (operator + embed) -
 * `ctx`/`i` for the record pager (AC-94-36), `includeTest` riding alongside
 * exactly like `brFormHref` (AC-94-40). */
export function buildIdeaFormQuery(opts?: {
  ctx?: string;
  index?: number;
  edit?: boolean;
  includeTest?: boolean;
}): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  if (opts?.includeTest) params.set('includeTest', '1');
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

/** Form href, optionally carrying record-nav context (ctx + index), edit mode
 * and the "Show test ideas" lane (AC-94-36). */
export function ideaFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean; includeTest?: boolean },
): string {
  return `${ideaFormPath(id)}${buildIdeaFormQuery(opts)}`;
}

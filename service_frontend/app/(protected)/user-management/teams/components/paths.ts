/** Route helpers for the Teams feature - single source of truth for its URLs. */

export const teamsListPath = '/user-management/teams';
export const teamNewPath = `${teamsListPath}/new`;
export const teamFormPath = (id: string) => `${teamsListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function teamFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${teamFormPath(id)}?${qs}` : teamFormPath(id);
}

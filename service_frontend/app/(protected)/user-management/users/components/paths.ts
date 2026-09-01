/** Route helpers for the Users feature - single source of truth for its URLs. */

export const usersListPath = '/user-management/users';
export const userNewPath = `${usersListPath}/new`;
export const userFormPath = (id: string) => `${usersListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function userFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${userFormPath(id)}?${qs}` : userFormPath(id);
}

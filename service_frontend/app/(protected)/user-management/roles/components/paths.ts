/** Route helpers for the Roles feature - single source of truth for its URLs. */

export const rolesListPath = '/user-management/roles';
export const roleNewPath = `${rolesListPath}/new`;
export const roleFormPath = (id: string) => `${rolesListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function roleFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${roleFormPath(id)}?${qs}` : roleFormPath(id);
}

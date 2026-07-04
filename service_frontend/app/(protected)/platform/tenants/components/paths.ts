/** Route helpers for the Platform → Tenants feature — single source of truth for its URLs. */

export const tenantsListPath = '/platform/tenants';
export const tenantNewPath = `${tenantsListPath}/new`;
export const tenantFormPath = (id: string) => `${tenantsListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function tenantFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${tenantFormPath(id)}?${qs}` : tenantFormPath(id);
}

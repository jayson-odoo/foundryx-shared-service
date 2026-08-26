/** Route helpers for the Integrations feature - single source of truth for its URLs. */

export const integrationsListPath = '/settings/integrations';
export const connectionNewPath = `${integrationsListPath}/new`;
export const connectionFormPath = (id: string) => `${integrationsListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function connectionFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${connectionFormPath(id)}?${qs}` : connectionFormPath(id);
}

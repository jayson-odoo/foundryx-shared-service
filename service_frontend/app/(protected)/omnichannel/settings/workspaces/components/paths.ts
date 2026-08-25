/** Route helpers for the Workspaces feature - single source of truth for its URLs. */

export const workspacesListPath = '/omnichannel/settings/workspaces';
export const workspaceNewPath = `${workspacesListPath}/new`;
export const workspaceFormPath = (id: string) => `${workspacesListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function workspaceFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${workspaceFormPath(id)}?${qs}` : workspaceFormPath(id);
}

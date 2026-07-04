export const WORKFLOWS_PATH = '/workflows';

export function workflowPath(id: string): string {
  return `${WORKFLOWS_PATH}/${id}`;
}

/** Form href preserving record-nav context (ctx + index), optionally edit mode. */
export function workflowFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${workflowPath(id)}?${qs}` : workflowPath(id);
}

export const TEMPLATES_PATH = '/settings/templates';

export function templatePath(id: string): string {
  return `${TEMPLATES_PATH}/${id}`;
}

/** Form href preserving record-nav context (ctx + index), optionally in edit mode. */
export function templateFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${templatePath(id)}?${qs}` : templatePath(id);
}

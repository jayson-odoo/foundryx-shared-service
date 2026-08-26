export const BR_PATH = '/ideation/business-requirements';

export function brPath(id: string): string {
  return `${BR_PATH}/${id}`;
}

/** Form href preserving record-nav context (ctx + index), optionally edit mode
 * and an initial tab (e.g. `grill` - Promote-to-BR lands on the Grill tab). */
export function brFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean; tab?: string },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.tab) params.set('tab', opts.tab);
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${brPath(id)}?${qs}` : brPath(id);
}

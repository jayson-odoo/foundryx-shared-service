export const FORMS_PATH = '/forms';

export function formPath(id: string): string {
  return `${FORMS_PATH}/${id}`;
}

/** Internal fill page (any authenticated user, D19). */
export function formFillPath(id: string): string {
  return `${formPath(id)}/fill`;
}

/** Public (anonymous) fill page — addressed by the form's per-tenant slug, on
 * whatever host the operator is on (the tenant subdomain in prod). slice 2. */
export function publicFormFillPath(slug: string): string {
  return `/public/forms/${slug}`;
}

/** Form href preserving record-nav context (ctx + index), optionally edit mode. */
export function formFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${formPath(id)}?${qs}` : formPath(id);
}

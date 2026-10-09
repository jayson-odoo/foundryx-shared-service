/** Route helpers for the Contacts module (plan 26) - single source of truth for its URLs. */

export const contactsListPath = '/omnichannel/contacts';
export const contactNewPath = `${contactsListPath}/new`;
export const contactFormPath = (id: string) => `${contactsListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index). */
export function contactFormHref(id: string, opts?: { ctx?: string; index?: number }): string {
  const params = new URLSearchParams();
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${contactFormPath(id)}?${qs}` : contactFormPath(id);
}

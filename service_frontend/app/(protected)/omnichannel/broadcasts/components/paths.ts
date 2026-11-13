/** Route helpers for the Broadcasts feature (plan 29) - single source of truth for its URLs. */

export const broadcastsListPath = '/omnichannel/broadcasts';
export const broadcastNewPath = `${broadcastsListPath}/new`;
export const broadcastFormPath = (id: string) => `${broadcastsListPath}/${id}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function broadcastFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${broadcastFormPath(id)}?${qs}` : broadcastFormPath(id);
}

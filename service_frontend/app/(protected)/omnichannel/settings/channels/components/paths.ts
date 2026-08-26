/** Route helpers for the Channels feature - single source of truth for its URLs. */

export const channelsListPath = '/omnichannel/settings/channels';
export const channelFormPath = (id: string) => `${channelsListPath}/${id}`;

/** Template builder routes (plan 07). */
export const templateNewPath = (channelId: string) =>
  `${channelFormPath(channelId)}/templates/new`;
export const templateEditPath = (channelId: string, templateId: string) =>
  `${channelFormPath(channelId)}/templates/${templateId}`;

/** Form href that preserves record-nav context (ctx + index), optionally in edit mode. */
export function channelFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${channelFormPath(id)}?${qs}` : channelFormPath(id);
}

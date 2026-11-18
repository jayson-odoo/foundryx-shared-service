import type { QuickReply } from '@/types/omnichannel';

/** How a quick reply is named in Foundryx UIUX toasts and countdowns: its
 *  shortcut, else the start of its message in quotes. */
export function fxQuickReplyName(
  item: Pick<QuickReply, 'shortcut' | 'body'>,
): string {
  if (item.shortcut?.trim()) return item.shortcut.trim();
  const body = item.body.trim();
  if (body.length <= 32) return `"${body}"`;
  // Cut at the last whole word inside the first 32 characters.
  const head = body.slice(0, 33);
  const cut = head.lastIndexOf(' ');
  return `"${(cut > 0 ? head.slice(0, cut) : head.slice(0, 32)).trimEnd()}..."`;
}

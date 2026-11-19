/**
 * Navigate the whole tab, not just this frame (lane FEEDBACK-SHARE-SS-HOST).
 *
 * The public share page is framed by the CRM's `/feedback/share/{token}`
 * page. After the phone check it moves the visitor to their board, whose URL
 * is on the CRM host: loading it inside the frame would show the CRM inside
 * itself. When framed, the TOP window navigates; if the browser refuses
 * (cross-origin top navigation without a recent click), it opens in a new tab
 * rather than nesting the CRM. Unframed = a plain navigation.
 * Returns false when nothing could be opened (popup blocked) so the caller
 * can refresh in place instead of leaving the visitor stuck.
 */
export interface NavWindow {
  top: NavWindow | null;
  self: NavWindow;
  location: { assign(url: string): void; href?: string };
  open(url: string, target?: string): { opener: unknown } | null;
}

export function navigateTop(url: string, win: NavWindow = window as unknown as NavWindow): boolean {
  let framed = false;
  try {
    framed = win.top !== null && win.top !== win.self;
  } catch {
    framed = true;
  }
  if (!framed || !win.top) {
    win.location.assign(url);
    return true;
  }
  try {
    win.top.location.href = url;
    return true;
  } catch {
    /* blocked by the browser: fall through */
  }
  // No 'noopener' feature: with it `open` always returns null, hiding a
  // blocked popup. The opener link is cut by hand instead.
  const opened = win.open(url, '_blank');
  if (!opened) return false;
  try {
    opened.opener = null;
  } catch {
    /* cross-origin already */
  }
  return true;
}

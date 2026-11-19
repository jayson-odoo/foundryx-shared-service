/**
 * Navigate the whole tab, not just this frame (lane FEEDBACK-SHARE-SS-HOST).
 *
 * The public share page is framed by the CRM's `/feedback/share/{token}`
 * page. After the phone check it moves the visitor to their board, whose URL
 * is on the CRM host: loading it inside the frame would show the CRM inside
 * itself. When framed, the TOP window navigates; if the browser refuses
 * (cross-origin top navigation without a recent click), it opens in a new tab
 * rather than nesting the CRM. Unframed = a plain navigation.
 */
export interface NavWindow {
  top: NavWindow | null;
  self: NavWindow;
  location: { assign(url: string): void; href?: string };
  open(url: string, target?: string, features?: string): unknown;
}

export function navigateTop(url: string, win: NavWindow = window as unknown as NavWindow): void {
  let framed = false;
  try {
    framed = win.top !== null && win.top !== win.self;
  } catch {
    framed = true;
  }
  if (!framed || !win.top) {
    win.location.assign(url);
    return;
  }
  try {
    win.top.location.href = url;
    return;
  } catch {
    /* blocked by the browser: fall through */
  }
  win.open(url, '_blank', 'noopener');
}

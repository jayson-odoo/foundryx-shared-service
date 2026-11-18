/**
 * The address-bar `ctx` each list last wrote itself (#259).
 *
 * A list with `urlState` writes its query with
 * `history.replaceState(history.state, ...)`: Next treats that as its own
 * entry, so no router action runs (a router RESTORE would discard a click
 * navigation that is still loading), but Next's `useSearchParams()` also never
 * sees the write. A list mounted again on the same page (Delivery: Pull only,
 * then Push) would then restore the PAGE-LOAD `ctx`. It restores from here
 * instead, only while the address bar still shows exactly what that same list
 * wrote on this path; otherwise (a navigation in flight, Back / Forward, an
 * edited URL) the router's `ctx` wins.
 */
interface Written {
  path: string;
  ctx: string;
}

const lastWritten = new Map<string, Written>();

/** Write the list's `ctx` to the address bar without a router action, and remember it. */
export function writeListUrlState(listKey: string, ctx: string): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('ctx', ctx);
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  lastWritten.set(listKey, { path: window.location.pathname, ctx });
}

/** This list's own last write, if the address bar still shows it on this path. */
export function liveListCtx(listKey: string | undefined): string | null {
  if (!listKey || typeof window === 'undefined') return null;
  const written = lastWritten.get(listKey);
  if (!written || written.path !== window.location.pathname) return null;
  return new URLSearchParams(window.location.search).get('ctx') === written.ctx ? written.ctx : null;
}

/**
 * Crew passes f39cccdf / c33ff4f2 (#259): a click on the link of the page you
 * are on (its sidebar entry) makes Next replace the URL without `ctx` while the
 * list stays mounted, so a reload showed the default list. Watching for the URL
 * change afterwards depends on how fast the route answers. Instead, cancel that
 * click's default in the capture phase: Next's Link still runs the link's own
 * onClick (e.g. closing the mobile sidebar), then skips its navigation because
 * the event is already default-prevented (`next/dist/client/app-dir/link.js`).
 * The URL never loses `ctx`, whatever the route timing. Only a plain left click
 * on a same-origin link to this exact path without its own `ctx` is affected.
 * Returns the cleanup.
 */
export function keepListCtxOnSamePathClick(): () => void {
  if (typeof window === 'undefined') return () => {};
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!anchor || (anchor.target && anchor.target !== '_self') || anchor.hasAttribute('download')) return;
    const to = new URL(anchor.href, window.location.href);
    if (to.origin !== window.location.origin || to.pathname !== window.location.pathname) return;
    if (to.searchParams.has('ctx') || to.hash) return;
    event.preventDefault();
  };
  document.addEventListener('click', onClick, true);
  return () => document.removeEventListener('click', onClick, true);
}

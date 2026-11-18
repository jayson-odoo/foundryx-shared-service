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

/** How long after a same-path link click the list watches the address bar. */
const SAME_PATH_WATCH_MS = 3000;
const SAME_PATH_POLL_MS = 50;

/**
 * Crew pass f39cccdf (#259): a click on the link of the page you are on (its
 * sidebar entry) makes Next replace the URL without `ctx` and keep the list
 * mounted. The router never knew `ctx`, so nothing in React changes: the list
 * would keep its state while the address bar lost it (a reload then showed the
 * default list). After such a click, write the list's current `ctx` back once
 * Next has replaced the URL. Returns the cleanup.
 */
export function keepListCtxOnSamePathClick(listKey: string, currentCtx: () => string): () => void {
  if (typeof window === 'undefined') return () => {};
  let timer: ReturnType<typeof setInterval> | null = null;
  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
  const onClick = (event: MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!anchor || (anchor.target && anchor.target !== '_self')) return;
    const to = new URL(anchor.href, window.location.href);
    const path = window.location.pathname;
    if (to.origin !== window.location.origin || to.pathname !== path || to.searchParams.has('ctx')) return;
    stop();
    const startedAt = Date.now();
    timer = setInterval(() => {
      if (window.location.pathname !== path || Date.now() - startedAt > SAME_PATH_WATCH_MS) {
        stop();
        return;
      }
      if (!new URLSearchParams(window.location.search).get('ctx')) writeListUrlState(listKey, currentCtx());
    }, SAME_PATH_POLL_MS);
  };
  document.addEventListener('click', onClick, true);
  return () => {
    document.removeEventListener('click', onClick, true);
    stop();
  };
}

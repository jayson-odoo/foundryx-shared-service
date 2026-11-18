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

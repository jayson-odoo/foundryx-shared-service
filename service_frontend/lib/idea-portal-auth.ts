/**
 * Idea portal session token store (lane IDEA-PORTAL). The portal token is the
 * Bearer for every `/portal/ideas/*` call. On the shared-service portal it is
 * kept in localStorage (30-day session, wrapped in try/catch - private windows
 * and blocked storage just mean signing in again); inside the Sorento iframe it
 * stays in memory only (`persist: false`), like the embed token.
 */
const STORAGE_KEY = 'fx.ideaPortal.token';

type Listener = (token: string | null) => void;

let current: string | null = null;
let persist = true;
let loaded = false;
const listeners = new Set<Listener>();

function load(): void {
  if (loaded) return;
  loaded = true;
  if (!persist || typeof window === 'undefined') return;
  try {
    current = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    current = null;
  }
}

export const ideaPortalAuth = {
  /** Embedded (iframe) mode: memory only, never written to storage. */
  setPersist(value: boolean): void {
    persist = value;
    if (!value) loaded = true;
  },
  get(): string | null {
    load();
    return current;
  },
  set(token: string | null): void {
    current = token;
    loaded = true;
    if (persist && typeof window !== 'undefined') {
      try {
        if (token) window.localStorage.setItem(STORAGE_KEY, token);
        else window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // storage blocked - the in-memory token still works for this tab
      }
    }
    listeners.forEach((l) => l(token));
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};

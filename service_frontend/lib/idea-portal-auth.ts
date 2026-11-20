/**
 * Idea portal session token store (lane IDEA-PORTAL). The portal token is the
 * Bearer for every `/portal/ideas/*` call.
 *
 * Shared-service portal: kept in localStorage TOGETHER with the staff user id
 * it was minted for (`owner`). The portal only reuses it while the SAME user is
 * signed in to the staff login - a sign-out or a different user on a shared
 * PC discards it (security review #2). Reads/writes are wrapped in try/catch:
 * private windows and blocked storage just mean exchanging again.
 * Sorento iframe (`persist: false`): memory only, like the embed token.
 */
const STORAGE_KEY = 'fx.ideaPortal.session';

type Listener = (token: string | null) => void;
interface Stored {
  token: string;
  owner: string | null;
}

let current: Stored | null = null;
let persist = true;
let loaded = false;
const listeners = new Set<Listener>();

function load(): void {
  if (loaded) return;
  loaded = true;
  if (!persist || typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<Stored>) : null;
    current = parsed && typeof parsed.token === 'string' ? { token: parsed.token, owner: parsed.owner ?? null } : null;
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
    return current?.token ?? null;
  },
  /** The staff user id the stored token was minted for. */
  owner(): string | null {
    load();
    return current?.owner ?? null;
  },
  set(token: string | null, owner: string | null = null): void {
    current = token ? { token, owner } : null;
    loaded = true;
    if (persist && typeof window !== 'undefined') {
      try {
        if (current) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
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

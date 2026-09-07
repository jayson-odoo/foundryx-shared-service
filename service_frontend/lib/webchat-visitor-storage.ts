/**
 * Visitor token storage for the web chat panel (plan 34 / A7b S4, D-A7B-4).
 * Scoped per widget key so a browser that has ever opened two different
 * channels' widgets never mixes their sessions. `localStorage` is the
 * PANEL's own (not the host page's - partitioned storage, D-A7B-4/D-A7B-30):
 * two tabs of the same website resolve the SAME token from the SAME
 * partitioned storage (AC-WEB-50) with no coordination needed.
 *
 * AC-WEB-49 - a browser that blocks storage entirely (private mode, a fully
 * partitioned/sandboxed iframe) falls back to an in-memory map for the life
 * of the tab: nothing throws, nothing shows an error, and the visitor can
 * still chat for as long as the tab stays open (the token just does not
 * survive a reload, which is the correct degraded behavior, not a bug).
 */
const memoryStore = new Map<string, string>();

let storageAvailable: boolean | null = null;

function storageOk(): boolean {
  if (storageAvailable !== null) return storageAvailable;
  if (typeof window === 'undefined') {
    storageAvailable = false;
    return false;
  }
  try {
    const probeKey = '__fx_webchat_probe__';
    window.localStorage.setItem(probeKey, '1');
    window.localStorage.removeItem(probeKey);
    storageAvailable = true;
  } catch {
    storageAvailable = false;
  }
  return storageAvailable;
}

function keyFor(widgetKey: string): string {
  return `fx-webchat-token:${widgetKey}`;
}

export function readVisitorToken(widgetKey: string): string | null {
  const key = keyFor(widgetKey);
  if (!storageOk()) return memoryStore.get(key) ?? null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memoryStore.get(key) ?? null;
  }
}

export function writeVisitorToken(widgetKey: string, token: string): void {
  const key = keyFor(widgetKey);
  if (!storageOk()) {
    memoryStore.set(key, token);
    return;
  }
  try {
    window.localStorage.setItem(key, token);
  } catch {
    memoryStore.set(key, token);
  }
}

export function clearVisitorToken(widgetKey: string): void {
  const key = keyFor(widgetKey);
  memoryStore.delete(key);
  if (!storageOk()) return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing to do - the in-memory copy is already cleared.
  }
}

/** Test-only reset (module-level cache + map survive across Vitest cases). */
export function __resetWebchatVisitorStorageForTests(): void {
  memoryStore.clear();
  storageAvailable = null;
}

'use client';

import { useSyncExternalStore } from 'react';

/**
 * Embed access-token store (sprint-4/11 §4). When the omnichannel embed shell
 * is mounted it holds the `/embed/session` access token IN MEMORY (never
 * localStorage, never the URL - contract §3) so the reused conversation service
 * + WebSocket authenticate as the external agent instead of the NextAuth
 * session.
 *
 * Mirrors {@link impersonationStore}: a module-level singleton that
 * `lib/api-client` + `conversation-service.real` read synchronously. Deliberately
 * NOT persisted - a refresh re-runs the postMessage handshake from scratch.
 */
export interface EmbedAuth {
  /** Short-lived (~15 min) bearer for the omnichannel API + WS. */
  accessToken: string;
  /** Workspace the token is scoped to (WS subscription + inbox fetch). */
  workspaceId: string;
  /** External-agent id - the self-claim ("assign to me") target in embed mode. */
  agentId: string;
}

type Listener = () => void;

let state: EmbedAuth | null = null;
const listeners = new Set<Listener>();

export const embedAuthStore = {
  getState(): EmbedAuth | null {
    return state;
  },
  /** Set/replace the whole embed session (first exchange). */
  set(auth: EmbedAuth | null): void {
    state = auth;
    listeners.forEach((fn) => fn());
  },
  /** Swap only the access token on a silent refresh (`needToken`→`token`). */
  setToken(accessToken: string): void {
    if (!state) return;
    state = { ...state, accessToken };
    listeners.forEach((fn) => fn());
  },
  clear(): void {
    if (state === null) return;
    state = null;
    listeners.forEach((fn) => fn());
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};

/** True when the current runtime is an embed widget (an embed session is set). */
export function isEmbedRuntime(): boolean {
  return state !== null;
}

export function useEmbedAuth(): EmbedAuth | null {
  return useSyncExternalStore(embedAuthStore.subscribe, embedAuthStore.getState, () => null);
}

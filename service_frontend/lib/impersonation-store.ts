'use client';

import { useSyncExternalStore } from 'react';

/**
 * Client-side impersonation session store (plan 03 §13). Holds the active
 * session (target + the target's effective permission keys) so the banner shows,
 * `useCan()` gates by the target, and `api-client` attaches the impersonation
 * header. Persisted to localStorage so a refresh keeps the session.
 */
export interface ImpersonationTargetUser {
  id: string;
  name: string | null;
  email: string;
  avatar: string | null;
  status: string;
}

export interface ImpersonationSession {
  sessionId: string;
  startedAt: string;
  targetUser: ImpersonationTargetUser;
  /** The target's effective permission keys - what the UI gates by while active. */
  permissions: string[];
}

const STORAGE_KEY = 'foundryx.impersonation.v1';
type Listener = () => void;

function readPersisted(): ImpersonationSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ImpersonationSession) : null;
  } catch {
    return null;
  }
}

function writePersisted(session: ImpersonationSession | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (session) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore quota / disabled storage
  }
}

let state: ImpersonationSession | null = readPersisted();
const listeners = new Set<Listener>();

export const impersonationStore = {
  getState(): ImpersonationSession | null {
    return state;
  },
  setSession(session: ImpersonationSession | null): void {
    state = session;
    writePersisted(session);
    listeners.forEach((fn) => fn());
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

export function useImpersonationSession(): ImpersonationSession | null {
  return useSyncExternalStore(
    impersonationStore.subscribe,
    impersonationStore.getState,
    () => null,
  );
}

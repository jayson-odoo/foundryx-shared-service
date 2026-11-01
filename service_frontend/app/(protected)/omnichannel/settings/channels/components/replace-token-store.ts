import { useSyncExternalStore } from 'react';
import type { Channel } from '@/types/omnichannel';

/**
 * The open Replace token request. The action registry only gets `run(rows, rt)`,
 * so a `run` records the request here and a host component beside the list or
 * the record renders the dialog.
 */
export interface ReplaceTokenRequest {
  channel: Channel;
  onReplaced: () => void;
}

let current: ReplaceTokenRequest | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export function openReplaceToken(request: ReplaceTokenRequest) {
  current = request;
  emit();
}

export function closeReplaceToken() {
  current = null;
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useReplaceTokenRequest(): ReplaceTokenRequest | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

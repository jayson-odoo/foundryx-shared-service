'use client';

/**
 * Whether the Advanced settings panel is open. A tiny shared store, so the
 * Theme panel's link (inside a popover or dialog that closes as the link is
 * used) can open a panel mounted elsewhere, which outlives it.
 */
import { useSyncExternalStore } from 'react';

let open = false;
const listeners = new Set<() => void>();

function emit(next: boolean): void {
  if (open === next) return;
  open = next;
  listeners.forEach((listener) => listener());
}

export const openFxAdvanced = (): void => emit(true);
export const closeFxAdvanced = (): void => emit(false);

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => open;
const serverSnapshot = () => false;

export function useFxAdvancedOpen(): boolean {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}

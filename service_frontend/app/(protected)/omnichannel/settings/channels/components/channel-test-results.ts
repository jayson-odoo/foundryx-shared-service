'use client';

/**
 * Foundryx UIUX switch only: the last "Test connection" result per channel,
 * so it can show next to the channel (its card, its Configuration tab)
 * instead of as a toast (gap audit 12: "Test connection is an Other Action;
 * its result shows next to it"). Kept for the page's life only; nothing is
 * stored. With the switch off nothing writes or reads it.
 */
import { useSyncExternalStore } from 'react';

export interface ChannelTestResult {
  ok: boolean;
  message: string;
  checkedAt: string;
}

let results: Record<string, ChannelTestResult | 'testing'> = {};
const listeners = new Set<() => void>();

function publish(next: Record<string, ChannelTestResult | 'testing'>): void {
  results = next;
  listeners.forEach((l) => l());
}

export function setChannelTesting(channelId: string): void {
  publish({ ...results, [channelId]: 'testing' });
}

export function setChannelTestResult(channelId: string, result: ChannelTestResult | null): void {
  const next = { ...results };
  if (result) next[channelId] = result;
  else delete next[channelId];
  publish(next);
}

export function useChannelTestResult(channelId: string | undefined): ChannelTestResult | 'testing' | undefined {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => (channelId ? results[channelId] : undefined),
    () => undefined,
  );
}

/** Test helper. */
export function resetChannelTestResults(): void {
  publish({});
}

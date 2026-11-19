'use client';

/**
 * Foundryx UIUX switch only: the last "Test connection" result per
 * connection, so it shows next to the connection (its card, its record's
 * Health card) instead of as a toast (gap audit 12: "Test connection is an
 * Other Action; its result shows next to it"). Kept for the page's life only;
 * nothing is stored. With the switch off nothing writes or reads it.
 */
import { useSyncExternalStore } from 'react';
import { integrationService } from '@/services/integration-service';
import type { TestConnectionResult } from '@/types/integration';

export type ConnectionTestState = TestConnectionResult | 'testing';

let results: Record<string, ConnectionTestState> = {};
const listeners = new Set<() => void>();

function publish(next: Record<string, ConnectionTestState>): void {
  results = next;
  listeners.forEach((l) => l());
}

/** The result key: a connection's plain check, or its targeted test. */
export const targetedKey = (connectionId: string) => `${connectionId}:target`;

export function setConnectionTesting(key: string): void {
  publish({ ...results, [key]: 'testing' });
}

export function setConnectionTestResult(key: string, result: TestConnectionResult | null): void {
  const next = { ...results };
  if (result) next[key] = result;
  else delete next[key];
  publish(next);
}

export function useConnectionTestResult(key: string | undefined): ConnectionTestState | undefined {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => (key ? results[key] : undefined),
    () => undefined,
  );
}

/**
 * Runs the test with the same request as the legacy look (`test(id)` or
 * `test(id, target)`) and keeps its result beside the action. A request that
 * fails outright keeps a plain failure line instead.
 */
export async function fxRunConnectionTest(
  connectionId: string,
  target?: string,
): Promise<TestConnectionResult | null> {
  const key = target === undefined ? connectionId : targetedKey(connectionId);
  setConnectionTesting(key);
  try {
    const result =
      target === undefined
        ? await integrationService.test(connectionId)
        : await integrationService.test(connectionId, target);
    setConnectionTestResult(key, result);
    return result;
  } catch (e) {
    setConnectionTestResult(key, {
      ok: false,
      message: e instanceof Error && e.message ? e.message : "Couldn't run the test. Try again.",
      checkedAt: new Date().toISOString(),
    });
    return null;
  }
}

/** Test helper. */
export function resetConnectionTestResults(): void {
  publish({});
}

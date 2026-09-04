'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { pendingActionsService } from '@/services/pending-actions-service';

/**
 * The grace window, from the caller's side (D2, AC-DLA-43).
 *
 * No confirmation dialog: `start()` parks the action on the server (one
 * `PendingAction` row per entity - a bulk selection parks ONE per row behind
 * a SINGLE shared countdown, D13) and the caller renders a countdown in its
 * place. Cancel withdraws it while the window is open; once the window
 * closes the server has already applied it (either the beat sweep or this
 * hook's own focus-poll of `current`, whichever gets there first) - the
 * commit is learned by re-reading `current`, never assumed from a local
 * timer (the same "server decides, not the client" contract as Sorento's
 * `useDeferredAction`).
 */

export interface DeferredEntity {
  entityType: string;
  entityId: string;
}

export type DeferredActionState =
  | { status: 'idle' }
  | {
      status: 'pending';
      actionKey: string;
      commitAt: string;
      windowSeconds: number;
      count: number;
    }
  | { status: 'committing'; count: number }
  | { status: 'done'; count: number }
  | { status: 'failed'; error: string };

export interface UseDeferredActionOptions {
  /**
   * Poll `current` from mount (not just after a click) - a record page does,
   * so a countdown started in another tab (or another surface on the same
   * record) shows here too. A list row does NOT set this - one hook per row
   * polling for a countdown nobody started would be one request per row.
   */
  watchFromMount?: boolean;
  /** The record(s) to watch when `watchFromMount` is set. */
  watch?: DeferredEntity;
  /** Called once the server has confirmed the action committed. */
  onCommitted?: () => void;
}

export interface UseDeferredActionResult {
  state: DeferredActionState;
  /** Entity ids currently parked under this hook's countdown - for a row/
   * card to key its own `data-pending` dimming off (D13, bulk). */
  dimEntityIds: string[];
  start: (
    actionKey: string,
    entities: DeferredEntity | DeferredEntity[],
    payload?: Record<string, unknown>,
  ) => Promise<{ commitAt: string; windowSeconds: number }>;
  cancel: () => Promise<void>;
  reset: () => void;
}

const POLL_MS = 1000;

export function useDeferredAction(
  options: UseDeferredActionOptions = {},
): UseDeferredActionResult {
  const { watchFromMount = false, watch, onCommitted } = options;
  const [state, setState] = useState<DeferredActionState>({ status: 'idle' });
  // The parked action ids (one per entity, D13) + which entities they belong
  // to - kept in a ref so the poll loop always reads the live set without
  // re-subscribing.
  const parkedRef = useRef<{ ids: string[]; entities: DeferredEntity[] } | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCommittedRef = useRef(onCommitted);
  onCommittedRef.current = onCommitted;

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const checkCurrent = useCallback(async (entity: DeferredEntity) => {
    try {
      return await pendingActionsService.current(entity.entityType, entity.entityId);
    } catch {
      return null;
    }
  }, []);

  const settle = useCallback(
    (status: 'done' | 'failed', count: number, error?: string) => {
      stopPolling();
      parkedRef.current = null;
      setState(
        status === 'done'
          ? { status: 'done', count }
          : { status: 'failed', error: error ?? 'The action failed.' },
      );
      if (status === 'done') onCommittedRef.current?.();
    },
    [stopPolling],
  );

  const pollOnce = useCallback(async () => {
    const parked = parkedRef.current;
    if (!parked || parked.entities.length === 0) return;
    // Every row in a bulk park shares the same commit_at/window, but EACH
    // has its OWN PendingAction row - under eager dev there is no beat
    // sweep, so `current()` is what lazily commits an overdue row, and it
    // only touches the ONE record it was asked about. Reading just the
    // first entity would leave the rest of a bulk batch parked forever
    // (found live: a 3-row bulk delete removed only 1 row from the list).
    // So every entity is checked, and the FIRST one still pending means
    // the whole batch is still counting down.
    const results = await Promise.all(parked.entities.map((e) => checkCurrent(e)));
    if (results.some((r) => r === null)) return;
    const stillPending = results.some((r) => r!.pending);
    if (stillPending) return;
    setState({ status: 'committing', count: parked.entities.length });
    const failed = results.find((r) => r!.lastOutcome?.status === 'failed');
    if (failed) {
      settle('failed', parked.entities.length, failed.lastOutcome!.errorText ?? 'The action failed.');
    } else {
      settle('done', parked.entities.length);
    }
  }, [checkCurrent, settle]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollTimerRef.current = setInterval(() => void pollOnce(), POLL_MS);
  }, [pollOnce, stopPolling]);

  // Focus-poll (AC-DLA-43): a second tab picks up the same countdown as soon
  // as the window regains focus, without waiting for the next 1s tick.
  useEffect(() => {
    function onFocus() {
      if (parkedRef.current) void pollOnce();
      else if (watchFromMount && watch) {
        void (async () => {
          const result = await checkCurrent(watch);
          if (result?.pending) {
            parkedRef.current = { ids: [result.pending.id], entities: [watch] };
            setState({
              status: 'pending',
              actionKey: result.pending.actionKey,
              commitAt: result.pending.commitAt,
              windowSeconds: result.pending.windowSeconds,
              count: 1,
            });
            startPolling();
          }
        })();
      }
    }
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [checkCurrent, pollOnce, startPolling, watch, watchFromMount]);

  // Watch from mount - a record page's countdown must reflect an action
  // already parked (another tab, or a re-mount mid-window).
  useEffect(() => {
    if (!watchFromMount || !watch) return;
    let cancelled = false;
    void (async () => {
      const result = await checkCurrent(watch);
      if (cancelled || !result?.pending) return;
      parkedRef.current = { ids: [result.pending.id], entities: [watch] };
      setState({
        status: 'pending',
        actionKey: result.pending.actionKey,
        commitAt: result.pending.commitAt,
        windowSeconds: result.pending.windowSeconds,
        count: 1,
      });
      startPolling();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- watch is a plain {type,id} pair, re-run only when it changes below
  }, [watchFromMount, watch?.entityType, watch?.entityId]);

  useEffect(() => stopPolling, [stopPolling]);

  const start = useCallback(
    async (
      actionKey: string,
      entities: DeferredEntity | DeferredEntity[],
      payload?: Record<string, unknown>,
    ) => {
      const list = Array.isArray(entities) ? entities : [entities];
      if (list.length === 0) {
        throw new Error('useDeferredAction.start() called with zero entities.');
      }
      const results = await Promise.all(
        list.map((e) =>
          pendingActionsService.park(actionKey, e.entityType, e.entityId, payload),
        ),
      );
      parkedRef.current = { ids: results.map((r) => r.id), entities: list };
      const first = results[0];
      setState({
        status: 'pending',
        actionKey,
        commitAt: first.commitAt,
        windowSeconds: first.windowSeconds,
        count: list.length,
      });
      startPolling();
      return { commitAt: first.commitAt, windowSeconds: first.windowSeconds };
    },
    [startPolling],
  );

  const cancel = useCallback(async () => {
    const parked = parkedRef.current;
    if (!parked) return;
    stopPolling();
    await Promise.allSettled(parked.ids.map((id) => pendingActionsService.cancel(id)));
    parkedRef.current = null;
    setState({ status: 'idle' });
  }, [stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    parkedRef.current = null;
    setState({ status: 'idle' });
  }, [stopPolling]);

  const dimEntityIds = parkedRef.current?.entities.map((e) => e.entityId) ?? [];

  return { state, dimEntityIds, start, cancel, reset };
}

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { pendingActionsService } from '@/services/pending-actions-service';
import type { PendingActionCreateResult } from '@/types/pending-actions';

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
  /**
   * Called when the server reports the action FAILED (a handler error, or
   * the target vanished before commit) - the caller shows an error toast.
   * Fix round 1 item 2: distinct from `onCommitted` (success) and silent
   * cancellation (below) - a failure must not be mistaken for a success.
   */
  onFailed?: (error: string) => void;
  /**
   * Called when `current` reports the action was CANCELLED - by this same
   * tab's own `cancel()` (which already resolves synchronously and does not
   * go through this callback) OR, the case this exists for, by ANOTHER tab/
   * teammate holding the same permission (D2 - anyone with the permission
   * may veto). The caller must reconcile its own toast/dim WITHOUT treating
   * it as a success (fix round 1 item 2 - a cancelled outcome was previously
   * reported as `done`, firing a success toast and navigating away).
   */
  onCancelledElsewhere?: () => void;
  /**
   * Called when THIS tab's own `cancel()` call itself failed - the window
   * had already closed server-side (AC-DLA-40 - a cancel arriving at/after
   * `commit_at` loses to the commit) or the request otherwise errored.
   * `cancel()` already reconciled by re-reading `current` (restoring the
   * countdown if it's somehow still pending, or settling done/failed) -
   * this is purely for the caller's error toast.
   */
  onCancelFailed?: (error: string) => void;
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
  ) => Promise<{
    commitAt: string;
    windowSeconds: number;
    failedCount: number;
    /** The entity ids that actually parked (fix round 1 item 3) - returned
     * directly rather than making the caller re-read `dimEntityIds` after
     * the await, which would read a stale closure from before this render. */
    parkedEntityIds: string[];
  }>;
  cancel: () => Promise<void>;
  reset: () => void;
}

const POLL_MS = 1000;
// N3: how many consecutive POST-lapse poll errors to tolerate before giving
// up on an unreachable `current()` and settling `failed` - a small grace so
// one blip right at the window's close doesn't fail the action.
const ERROR_GRACE_POLLS = 2;

export function useDeferredAction(
  options: UseDeferredActionOptions = {},
): UseDeferredActionResult {
  const {
    watchFromMount = false,
    watch,
    onCommitted,
    onFailed,
    onCancelledElsewhere,
    onCancelFailed,
  } = options;
  const [state, setState] = useState<DeferredActionState>({ status: 'idle' });
  // The parked action ids (one per entity, D13) + which entities they belong
  // to - kept in a ref so the poll loop always reads the live set without
  // re-subscribing.
  const parkedRef = useRef<{ ids: string[]; entities: DeferredEntity[]; commitAt: string } | null>(
    null,
  );
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // N3: consecutive `current()` failures since the window lapsed - reset on
  // every poll that gets a real answer, and on every fresh park/watch.
  const lapsedErrorPollsRef = useRef(0);
  const onCommittedRef = useRef(onCommitted);
  onCommittedRef.current = onCommitted;
  const onFailedRef = useRef(onFailed);
  onFailedRef.current = onFailed;
  const onCancelledElsewhereRef = useRef(onCancelledElsewhere);
  onCancelledElsewhereRef.current = onCancelledElsewhere;
  const onCancelFailedRef = useRef(onCancelFailed);
  onCancelFailedRef.current = onCancelFailed;

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
      else onFailedRef.current?.(error ?? 'The action failed.');
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
    if (results.some((r) => r === null)) {
      // N3: `current()` itself errored (e.g. a 404 after the actor's
      // permission - or the module - was revoked mid-countdown). The old
      // `return` here left the hook stuck in `pending` FOREVER: no toast,
      // no navigation, an unkillable countdown. A blip while the window is
      // still counting down is tolerated silently (the next tick likely
      // succeeds); only once the window has actually lapsed AND a couple
      // more polls keep failing does this give up and settle `failed` -
      // the caller gets an explicit message instead of nothing.
      const lapsed = Date.parse(parked.commitAt) <= Date.now();
      if (!lapsed) return;
      lapsedErrorPollsRef.current += 1;
      if (lapsedErrorPollsRef.current > ERROR_GRACE_POLLS) {
        settle('failed', parked.entities.length, "Could not confirm the action's outcome.");
      }
      return;
    }
    lapsedErrorPollsRef.current = 0;
    const stillCountingDown = results.some((r) => r!.pending && r!.pending.status !== 'committing');
    if (stillCountingDown) return;
    // Fix round 2, B1: at least one row was CLAIMED (beat sweep, or a
    // racing `current` poll from another tab) but hasn't settled yet - the
    // handler may still be running, and may still fail. Report `committing`
    // (non-terminal: no toast, no navigation) and keep polling; NEVER read
    // this as a settled outcome (previously `current()` surfaced the claimed
    // row as a `lastOutcome` that wasn't cancelled/failed, which this hook
    // read as `done` mid-commit - and even if the commit then failed).
    const stillCommitting = results.some((r) => r!.pending?.status === 'committing');
    if (stillCommitting) {
      setState({ status: 'committing', count: parked.entities.length });
      return;
    }
    // Defensive: a `lastOutcome.status` of `'committing'` should never reach
    // here (the backend's `current()` never returns it there), but treat it
    // as still in-flight rather than settled if it ever does.
    const stillCommittingOutcome = results.some(
      (r) => r!.lastOutcome?.status === 'committing',
    );
    if (stillCommittingOutcome) {
      setState({ status: 'committing', count: parked.entities.length });
      return;
    }
    // Fix round 1 item 2: a CANCELLED outcome (this hook's own `cancel()`
    // already short-circuits before ever polling again - this is a
    // teammate cancelling from ANOTHER tab/session) must return to `idle`
    // silently, never report `done` (which would fire a success toast and
    // navigate away from a record that was NOT deleted).
    const cancelledElsewhere = results.some((r) => r!.lastOutcome?.status === 'cancelled');
    if (cancelledElsewhere) {
      stopPolling();
      parkedRef.current = null;
      setState({ status: 'idle' });
      onCancelledElsewhereRef.current?.();
      return;
    }
    setState({ status: 'committing', count: parked.entities.length });
    const failed = results.find((r) => r!.lastOutcome?.status === 'failed');
    if (failed) {
      settle('failed', parked.entities.length, failed.lastOutcome!.errorText ?? 'The action failed.');
    } else {
      settle('done', parked.entities.length);
    }
  }, [checkCurrent, settle, stopPolling]);

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
            parkedRef.current = {
              ids: [result.pending.id],
              entities: [watch],
              commitAt: result.pending.commitAt,
            };
            lapsedErrorPollsRef.current = 0;
            // B1: found already mid-commit (the beat sweep claimed it just
            // before this focus-poll) - report `committing`, not a
            // countdown against an already-past `commitAt`.
            setState(
              result.pending.status === 'committing'
                ? { status: 'committing', count: 1 }
                : {
                    status: 'pending',
                    actionKey: result.pending.actionKey,
                    commitAt: result.pending.commitAt,
                    windowSeconds: result.pending.windowSeconds,
                    count: 1,
                  },
            );
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
      parkedRef.current = {
        ids: [result.pending.id],
        entities: [watch],
        commitAt: result.pending.commitAt,
      };
      lapsedErrorPollsRef.current = 0;
      setState(
        result.pending.status === 'committing'
          ? { status: 'committing', count: 1 }
          : {
              status: 'pending',
              actionKey: result.pending.actionKey,
              commitAt: result.pending.commitAt,
              windowSeconds: result.pending.windowSeconds,
              count: 1,
            },
      );
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
      // Fix round 1 item 3: `Promise.all` would orphan every row that DID
      // park the instant ANY one park rejects (a 409 mid-batch) - the
      // rejection unwinds the whole call and `parkedRef` is never set, so
      // the rows that succeeded server-side count down with no Cancel and
      // no visible countdown anywhere in the UI. `allSettled` keeps every
      // successful park tracked; only the failures are reported.
      const settled = await Promise.allSettled(
        list.map((e) =>
          pendingActionsService.park(actionKey, e.entityType, e.entityId, payload),
        ),
      );
      const succeeded: { entity: DeferredEntity; result: PendingActionCreateResult }[] = [];
      let failedCount = 0;
      let firstError: unknown;
      settled.forEach((outcome, i) => {
        if (outcome.status === 'fulfilled') {
          succeeded.push({ entity: list[i], result: outcome.value });
        } else {
          failedCount += 1;
          firstError = firstError ?? outcome.reason;
        }
      });
      if (succeeded.length === 0) {
        throw firstError instanceof Error
          ? firstError
          : new Error('Could not start that action.');
      }
      const first = succeeded[0].result;
      parkedRef.current = {
        ids: succeeded.map((s) => s.result.id),
        entities: succeeded.map((s) => s.entity),
        commitAt: first.commitAt,
      };
      lapsedErrorPollsRef.current = 0;
      setState({
        status: 'pending',
        actionKey,
        commitAt: first.commitAt,
        windowSeconds: first.windowSeconds,
        count: succeeded.length,
      });
      startPolling();
      return {
        commitAt: first.commitAt,
        windowSeconds: first.windowSeconds,
        failedCount,
        parkedEntityIds: succeeded.map((s) => s.entity.entityId),
      };
    },
    [startPolling],
  );

  const cancel = useCallback(async () => {
    const parked = parkedRef.current;
    if (!parked) return;
    // Fix round 1 item 9: leave `pending` SYNCHRONOUSLY - the button/fill
    // reverts on the SAME click, matching the toast surface's own
    // `dismissDeferredToast` (called synchronously by its caller). Waiting
    // for the round trip left the fill draining at full speed for the whole
    // request, sometimes reaching zero and flipping to "Deleting…" AFTER
    // the user had already cancelled.
    stopPolling();
    parkedRef.current = null;
    setState({ status: 'idle' });

    const results = await Promise.allSettled(
      parked.ids.map((id) => pendingActionsService.cancel(id)),
    );
    const anyFailed = results.some((r) => r.status === 'rejected');
    if (!anyFailed) return;

    // Reconcile: a cancel that arrives AT/AFTER the window closes loses to
    // the commit (AC-DLA-40) - re-read `current` rather than trusting the
    // optimistic "idle" we already rendered, so the UI never shows
    // "cancelled" for a record that was actually deleted.
    const first = parked.entities[0];
    const outcome = first ? await checkCurrent(first) : null;
    if (outcome?.pending) {
      parkedRef.current = {
        ids: parked.ids,
        entities: parked.entities,
        commitAt: outcome.pending.commitAt,
      };
      lapsedErrorPollsRef.current = 0;
      setState({
        status: 'pending',
        actionKey: outcome.pending.actionKey,
        commitAt: outcome.pending.commitAt,
        windowSeconds: outcome.pending.windowSeconds,
        count: parked.entities.length,
      });
      startPolling();
      onCancelFailedRef.current?.('Could not cancel - please try again.');
      return;
    }
    if (outcome?.lastOutcome?.status === 'failed') {
      onCancelFailedRef.current?.('Could not cancel - the action already ran.');
      onFailedRef.current?.(outcome.lastOutcome.errorText ?? 'The action failed.');
      return;
    }
    if (outcome?.lastOutcome?.status === 'cancelled') {
      // Someone else's cancel won the race - the net effect (not pending,
      // nothing applied) matches the optimistic "idle" already rendered, so
      // there's nothing further to reconcile.
      return;
    }
    onCancelFailedRef.current?.('Could not cancel - the action already ran.');
    onCommittedRef.current?.();
  }, [checkCurrent, startPolling, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    parkedRef.current = null;
    lapsedErrorPollsRef.current = 0;
    setState({ status: 'idle' });
  }, [stopPolling]);

  const dimEntityIds = parkedRef.current?.entities.map((e) => e.entityId) ?? [];

  return { state, dimEntityIds, start, cancel, reset };
}

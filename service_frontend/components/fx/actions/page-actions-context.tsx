'use client';

/**
 * Who owns the page header's actions (playbook 0.71.0 "Actions": one Main
 * Action per page, "Never twice").
 *
 * Any component on the page (a list config, a drawer, a tab) registers the
 * page's red action or its Other Actions; the Foundryx UIUX page header shows
 * them. One page is on screen at a time, so this is one small store, not a
 * provider: nothing has to be mounted, and with the switch off nothing reads
 * it.
 *
 * - Main action: the most recent registration wins; when it unregisters, the
 *   one before it comes back. Only one ever shows.
 * - Hidden while a dialog or an in-panel submit is open
 *   (`useHideMainAction(true)`), so the page never shows two red actions.
 */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import type { FxIconRef } from '@/components/fx/icons';

export interface FxBlocked {
  /** The "why" under the button, e.g. "Tick at least one client." */
  reason: string;
  /** `data-fx-pulse-target` value of the thing it waits for. Omit when nothing
   *  on the page can unblock it (already sent, already paid). */
  pulseTarget?: string;
}

export interface FxMainActionSpec {
  id: string;
  /** Short label at rest ("Record payment"). */
  label: string;
  /** The full action with object and amount ("Record RM 2,500.00 from Client
   *  E"), shown on hover and focus and always given to screen readers. */
  fullLabel?: string;
  onClick?: () => void;
  /** Submits this form id instead of running `onClick`. */
  form?: string;
  blocked?: FxBlocked;
  working?: boolean;
}

export interface FxOtherActionSpec {
  id: string;
  label: string;
  /** A meaning (`'snooze'`, `'csv-down'`), or a drawn icon node for a
   *  meaning the set does not hold. */
  icon: FxIconRef;
  onClick: () => void;
  /** Greyed with its reason as the tooltip. */
  disabledReason?: string;
  /** The × that turns red with "Delete". */
  tone?: 'delete';
}

interface Entry<V> {
  key: number;
  value: V;
}

interface Snapshot {
  main: FxMainActionSpec | null;
  others: FxOtherActionSpec[];
  /** Other Action ids the page config keeps in the More menu
   *  (`fx.moreActionIds`), whatever the count. */
  moreIds: string[];
  hidden: boolean;
}

interface OthersValue {
  actions: FxOtherActionSpec[];
  moreIds: string[];
}

const NO_IDS: string[] = [];

let mains: Entry<FxMainActionSpec>[] = [];
let others: Entry<OthersValue>[] = [];
let hiders = 0;
let seq = 0;
let snapshot: Snapshot = { main: null, others: [], moreIds: NO_IDS, hidden: false };
const listeners = new Set<() => void>();

function publish(): void {
  snapshot = {
    main: mains.length ? mains[mains.length - 1].value : null,
    others: others.flatMap((entry) => entry.value.actions),
    moreIds: others.some((entry) => entry.value.moreIds.length)
      ? others.flatMap((entry) => entry.value.moreIds)
      : NO_IDS,
    hidden: hiders > 0,
  };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: Snapshot = { main: null, others: [], moreIds: NO_IDS, hidden: false };

/** What the page header shows: the one main action, the other actions, and
 *  whether the main action is hidden behind an open dialog. */
export function usePageActions(): Snapshot {
  return useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => EMPTY,
  );
}

function upsert<V>(list: Entry<V>[], key: number, value: V): Entry<V>[] {
  const index = list.findIndex((entry) => entry.key === key);
  if (index === -1) return [...list, { key, value }];
  const next = list.slice();
  next[index] = { key, value };
  return next;
}

function useKey(): number {
  const ref = useRef(0);
  if (ref.current === 0) {
    seq += 1;
    ref.current = seq;
  }
  return ref.current;
}

/** Makes `action` the page's red action while the caller is mounted. Pass
 *  null to give it up (for example while a tab is not shown). */
export function useRegisterMainAction(action: FxMainActionSpec | null): void {
  const key = useKey();
  useEffect(() => {
    mains = action
      ? upsert(mains, key, action)
      : mains.filter((entry) => entry.key !== key);
    publish();
  }, [key, action]);
  useEffect(
    () => () => {
      mains = mains.filter((entry) => entry.key !== key);
      publish();
    },
    [key],
  );
}

/** Adds icon actions beside the red action, in order of use. `moreIds`
 *  (the page config's `fx.moreActionIds`) always sit in the More menu; they
 *  may name actions another caller registers. */
export function useRegisterOtherActions(
  actions: FxOtherActionSpec[],
  moreIds: string[] = NO_IDS,
): void {
  const key = useKey();
  useEffect(() => {
    others = upsert(others, key, { actions, moreIds });
    publish();
  }, [key, actions, moreIds]);
  useEffect(
    () => () => {
      others = others.filter((entry) => entry.key !== key);
      publish();
    },
    [key],
  );
}

/** Hides the header's red action while `active` (a dialog or an in-panel
 *  submit is the page's one action meanwhile). */
export function useHideMainAction(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    hiders += 1;
    publish();
    return () => {
      hiders -= 1;
      publish();
    };
  }, [active]);
}

/** Test helper: forgets every registration. */
export function resetPageActionsForTests(): void {
  mains = [];
  others = [];
  hiders = 0;
  publish();
}

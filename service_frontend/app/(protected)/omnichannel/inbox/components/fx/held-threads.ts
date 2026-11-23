'use client';

/**
 * Rows that never move under the pointer (Foundryx UIUX, gap audit 15 "Lists
 * that update by themselves", owner choice: a "3 new" pill instead of
 * re-sorting under the pointer).
 *
 * While the list is held (the pointer is on it, or it is scrolled down), its
 * order is frozen: a changed row updates in place, a row that left the list
 * goes, and a new row or a row with a newer message waits. Those waiting rows
 * are counted for the pill; clicking the pill (or letting go of the list while
 * it is scrolled to the top) shows the list in its live order.
 *
 * Only what is drawn is held. The fetches, the live feed and the server order
 * are untouched (`useConversations`), so the same requests run in both looks.
 */
import { useCallback, useState } from 'react';
import type { ConversationThread } from '@/types/omnichannel';

/** The frozen order and each row's last message time when it froze. */
export interface HeldOrder {
  ids: string[];
  lastAt: Map<string, string>;
}

export function holdOrder(threads: ConversationThread[]): HeldOrder {
  return {
    ids: threads.map((t) => t.id),
    lastAt: new Map(threads.map((t) => [t.id, t.lastMessageAt ?? ''])),
  };
}

/** The rows to draw for a frozen order: the frozen rows in their frozen
 *  places with their live values; rows that left are dropped; new rows wait. */
export function heldRows(
  held: HeldOrder,
  threads: ConversationThread[],
): ConversationThread[] {
  const live = new Map(threads.map((t) => [t.id, t]));
  const rows: ConversationThread[] = [];
  for (const id of held.ids) {
    const row = live.get(id);
    if (row) rows.push(row);
  }
  return rows;
}

/** How many rows wait to move up: rows not in the frozen order, and rows
 *  whose last message is newer than when the order froze. */
export function countWaiting(
  held: HeldOrder,
  threads: ConversationThread[],
): number {
  let n = 0;
  for (const t of threads) {
    const was = held.lastAt.get(t.id);
    if (was === undefined || (t.lastMessageAt ?? '') > was) n += 1;
  }
  return n;
}

export interface UseHeldThreadsResult {
  rows: ConversationThread[];
  /** Rows waiting for the pill (0 when nothing waits or nothing is held). */
  waiting: number;
  /** Shows the live order now (the pill's click). */
  release: () => void;
}

/**
 * `threads` is the live list, `holding` whether the list may not move now,
 * `resetKey` changes with the filters (the first list after a change is a new
 * list, never "new" rows).
 */
export function useHeldThreads(
  threads: ConversationThread[],
  holding: boolean,
  resetKey: string,
): UseHeldThreadsResult {
  const [held, setHeld] = useState<HeldOrder | null>(() =>
    holding ? holdOrder(threads) : null,
  );
  const [prevHolding, setPrevHolding] = useState(holding);
  const [prevKey, setPrevKey] = useState(resetKey);
  const [prevThreads, setPrevThreads] = useState(threads);
  // The list that answers a filter change (or the first load) has not
  // arrived yet.
  const [awaitingFresh, setAwaitingFresh] = useState(threads.length === 0);

  // Derived state from changed inputs, adjusted during render (React's
  // sanctioned pattern), so a frame never shows the wrong order.
  if (holding !== prevHolding) {
    setPrevHolding(holding);
    setHeld(holding ? holdOrder(threads) : null);
  }
  if (resetKey !== prevKey) {
    setPrevKey(resetKey);
    setAwaitingFresh(true);
  }
  if (threads !== prevThreads) {
    setPrevThreads(threads);
    if (awaitingFresh) {
      setAwaitingFresh(false);
      if (held) setHeld(holdOrder(threads));
    }
  }

  const release = useCallback(() => {
    setHeld(holding ? holdOrder(threads) : null);
  }, [holding, threads]);

  if (!held) return { rows: threads, waiting: 0, release };
  return {
    rows: heldRows(held, threads),
    waiting: countWaiting(held, threads),
    release,
  };
}

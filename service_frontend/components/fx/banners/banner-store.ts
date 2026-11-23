'use client';

/**
 * System banners (playbook 0.71.0 "System banners"): messages about the whole
 * system or session, shown one at a time in one bar above the top bar.
 *
 * Any component registers a banner while it is true (`useSystemBanner`); the
 * host (`FxSystemBannerHost`) shows the most urgent one: the `warn` set
 * (something to act on, or that limits you) before the `info` set (news), in
 * order of arrival within each. News can be closed and stays closed for that
 * message (per browser); a banner about something still true has no close
 * and leaves by itself once it stops being true.
 *
 * One page is on screen at a time, so this is one small store, not a
 * provider; with the switch off nothing reads it.
 */
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from 'react';

export type FxBannerTone = 'warn' | 'info';

export interface FxBannerAction {
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
}

export interface FxBanner {
  /** Stable per message: a closed news banner stays closed by this id. */
  id: string;
  tone: FxBannerTone;
  /** One line: what is happening and when. */
  text: ReactNode;
  /** At most one text button at the right. */
  action?: FxBannerAction;
  /** News only: shows × and stays closed once closed. */
  closable?: boolean;
  /** An extra icon control of SS's own (the impersonation "Hide banner"). */
  hide?: { label: string; onHide: () => void };
}

interface Entry {
  key: number;
  banner: FxBanner;
}

export const FX_BANNERS_CLOSED_KEY = 'fx_banners_closed';

let entries: Entry[] = [];
let closed: Set<string> | null = null;
let seq = 0;
let snapshot: FxBanner[] = [];
const listeners = new Set<() => void>();

function closedIds(): Set<string> {
  if (closed) return closed;
  closed = new Set();
  try {
    const raw = window.localStorage.getItem(FX_BANNERS_CLOSED_KEY);
    const ids: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(ids)) {
      ids.forEach((id) => typeof id === 'string' && closed?.add(id));
    }
  } catch {
    // Unreadable storage: nothing is remembered as closed.
  }
  return closed;
}

const RANK: Record<FxBannerTone, number> = { warn: 0, info: 1 };

/** The banners to show, most urgent first (pure, unit-tested). */
export function orderBanners(
  list: FxBanner[],
  closedSet: ReadonlySet<string>,
): FxBanner[] {
  return list
    .filter((banner) => !(banner.closable && closedSet.has(banner.id)))
    .map((banner, index) => ({ banner, index }))
    .sort((a, b) => RANK[a.banner.tone] - RANK[b.banner.tone] || a.index - b.index)
    .map(({ banner }) => banner);
}

function publish(): void {
  snapshot = orderBanners(
    entries.map((entry) => entry.banner),
    closedIds(),
  );
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: FxBanner[] = [];

/** The banners to show now, most urgent first. */
export function useSystemBanners(): FxBanner[] {
  return useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => EMPTY,
  );
}

/** Closes a news banner for good (this browser). */
export function closeSystemBanner(id: string): void {
  const set = closedIds();
  set.add(id);
  try {
    window.localStorage.setItem(
      FX_BANNERS_CLOSED_KEY,
      JSON.stringify(Array.from(set).slice(-50)),
    );
  } catch {
    // Storage blocked: it stays closed for this page only.
  }
  publish();
}

/** Shows `banner` while the caller is mounted and passes it; null shows none. */
export function useSystemBanner(banner: FxBanner | null): void {
  const key = useRef(0);
  if (key.current === 0) {
    seq += 1;
    key.current = seq;
  }
  const k = key.current;
  useEffect(() => {
    const at = entries.findIndex((entry) => entry.key === k);
    if (!banner) {
      entries = entries.filter((entry) => entry.key !== k);
    } else if (at === -1) {
      entries = [...entries, { key: k, banner }];
    } else {
      // An update keeps its place in the arrival order.
      entries = entries.map((entry) =>
        entry.key === k ? { key: k, banner } : entry,
      );
    }
    publish();
  }, [k, banner]);
  useEffect(
    () => () => {
      entries = entries.filter((entry) => entry.key !== k);
      publish();
    },
    [k],
  );
}

/** Test helper: forgets every banner and every closed id. */
export function resetSystemBannersForTests(): void {
  entries = [];
  closed = null;
  publish();
}

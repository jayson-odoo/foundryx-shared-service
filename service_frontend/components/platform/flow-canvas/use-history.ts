'use client';

/**
 * Generic snapshot undo/redo for a controlled value (BL-064 — the shared
 * position/layout history both FlowCanvas consumers use: the workflow canvas
 * over its whole draft doc, the status canvas over its positions map).
 *
 * The value is owned by the parent (controlled). `set` records the prior value
 * on the undo stack and forwards the new one through `onChange`. A value change
 * that DIDN'T come through `set` (a fresh load, a Cancel/discard) is detected
 * via the `lastEmitted` ref and resets both stacks — the timeline belongs to
 * the current editing session, not to externally-swapped state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface History<T> {
  /** Push a new value (records the current one for undo, clears redo). */
  set: (next: T) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Forget the timeline (e.g. after a successful save commits the baseline). */
  reset: () => void;
}

export function useHistory<T>(value: T, onChange: (next: T) => void): History<T> {
  const [past, setPast] = useState<T[]>([]);
  const [future, setFuture] = useState<T[]>([]);
  const lastEmitted = useRef<T | null>(null);

  useEffect(() => {
    if (lastEmitted.current !== null && value !== lastEmitted.current) {
      setPast([]);
      setFuture([]);
      lastEmitted.current = null;
    }
  }, [value]);

  const set = useCallback(
    (next: T) => {
      lastEmitted.current = next;
      setPast((p) => [...p, value]);
      setFuture([]);
      onChange(next);
    },
    [value, onChange],
  );

  const undo = useCallback(() => {
    setPast((p) => {
      if (!p.length) return p;
      const prev = p[p.length - 1];
      lastEmitted.current = prev;
      setFuture((f) => [value, ...f]);
      onChange(prev);
      return p.slice(0, -1);
    });
  }, [value, onChange]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (!f.length) return f;
      const next = f[0];
      lastEmitted.current = next;
      setPast((p) => [...p, value]);
      onChange(next);
      return f.slice(1);
    });
  }, [value, onChange]);

  const reset = useCallback(() => {
    setPast([]);
    setFuture([]);
    lastEmitted.current = null;
  }, []);

  const canUndo = past.length > 0;
  const canRedo = future.length > 0;
  // Stable identity (only changes when something it exposes changes) so
  // consumers' effects keyed on the hook don't re-subscribe every render.
  return useMemo(
    () => ({ set, undo, redo, canUndo, canRedo, reset }),
    [set, undo, redo, canUndo, canRedo, reset],
  );
}

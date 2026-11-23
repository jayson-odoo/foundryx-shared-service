'use client';

/**
 * The side panel's icon rail (playbook 0.71.0 "Left side panel").
 *
 * - Hover (or keyboard focus inside it) opens it at once.
 * - When the pointer leaves: wait (setting "Wait before it folds to icons",
 *   0.3 s), then it slides shut; the slide itself (0.65 s) is CSS.
 * - Pinned, it never hides. The pin is remembered per browser.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export const FX_RAIL_PIN_KEY = 'fx_rail_pinned';

function readPinned(): boolean {
  try {
    return window.localStorage.getItem(FX_RAIL_PIN_KEY) === '1';
  } catch {
    return false;
  }
}

function writePinned(pinned: boolean): void {
  try {
    if (pinned) window.localStorage.setItem(FX_RAIL_PIN_KEY, '1');
    else window.localStorage.removeItem(FX_RAIL_PIN_KEY);
  } catch {
    // Storage blocked: the pin lasts for this page only.
  }
}

export interface FxRail {
  /** Open as a full panel (pinned, hovered or focused). */
  expanded: boolean;
  pinned: boolean;
  togglePin: () => void;
  /** Spread on the panel element. */
  handlers: {
    onPointerEnter: (event: { pointerType: string }) => void;
    onPointerLeave: (event: { pointerType: string }) => void;
    onPointerDown: () => void;
    onFocus: () => void;
    onBlur: (event: {
      currentTarget: Element;
      relatedTarget: EventTarget | null;
    }) => void;
  };
}

/** `waitSeconds`: the pause after the pointer leaves before it folds. */
export function useRail(waitSeconds: number): FxRail {
  const [pinned, setPinned] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keyboardInside = useRef(false);
  const pointerDown = useRef(false);

  useEffect(() => {
    setPinned(readPinned());
  }, []);

  const cancel = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const show = useCallback(() => {
    cancel();
    setOpen(true);
  }, [cancel]);

  const hideSoon = useCallback(() => {
    cancel();
    timer.current = setTimeout(
      () => {
        timer.current = null;
        setOpen(false);
      },
      Math.max(0, waitSeconds * 1000),
    );
  }, [cancel, waitSeconds]);

  const togglePin = useCallback(() => {
    const next = !pinned;
    writePinned(next);
    setPinned(next);
  }, [pinned]);

  const handlers: FxRail['handlers'] = {
    onPointerEnter: (event) => {
      if (event.pointerType === 'touch') return;
      show();
    },
    onPointerLeave: (event) => {
      if (event.pointerType === 'touch') return;
      if (keyboardInside.current) return;
      hideSoon();
    },
    onPointerDown: () => {
      pointerDown.current = true;
      keyboardInside.current = false;
    },
    onFocus: () => {
      // A click focuses what it lands on; only keyboard focus holds it open.
      if (pointerDown.current) {
        pointerDown.current = false;
        return;
      }
      keyboardInside.current = true;
      show();
    },
    onBlur: (event) => {
      const next = event.relatedTarget;
      if (next instanceof Node && event.currentTarget.contains(next)) return;
      keyboardInside.current = false;
      hideSoon();
    },
  };

  return { expanded: pinned || open, pinned, togglePin, handlers };
}

'use client';

/**
 * Hold to Copy (playbook 0.71.0 "Lists > Hold to Copy").
 *
 * Wraps a value people may want to copy (a reference, a name, an amount, a
 * date). With the Foundryx UIUX switch off, or the "Hold to Copy" setting
 * off, it renders its children untouched.
 *
 * - **Where it reacts:** the text itself plus the reach around it (setting
 *   "Reach around the text", 8px), so short values are easy to hit.
 * - **Hover:** a small copy icon rides 10px right of and 24px above the
 *   pointer on the Tool Background (no edge, see-through, fading out at its
 *   rim; solid with reduced transparency or more contrast).
 * - **Hold** for the hold time (0.75 s): a ring runs clockwise round the
 *   icon, then the icon turns into "Copied", which shows for 1.4 s. On touch
 *   the icon sits above the finger.
 * - **Cancelling:** moving more than 6px or letting go early. The click that
 *   ends a hold never opens a link or row under it.
 * - **Copying:** the visible text only (screen-reader-only words and
 *   `data-fx-no-copy` parts are left out). If the clipboard is refused the
 *   browser's copy command is tried; if both fail the tip says
 *   "Couldn't copy".
 * - The value cannot be selected as text, so a long press on a phone never
 *   starts a selection.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { Copy } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useFxSetting } from '@/hooks/use-fx';

/** Pointer travel (px) that cancels a hold. */
export const FX_H2C_MOVE_CANCEL = 6;

/** The text a value shows, without screen-reader-only or no-copy parts. */
export function fxVisibleText(el: Element): string {
  const clone = el.cloneNode(true) as Element;
  clone.querySelectorAll('.sr-only, [data-fx-no-copy]').forEach((n) => n.remove());
  return (clone.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/** Copies text: the clipboard first, then the browser's copy command. */
export async function fxCopyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Refused (for example inside a frame): fall back below.
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.className = 'fixed start-0 top-0 opacity-0';
    document.body.appendChild(area);
    area.select();
    const ok = typeof document.execCommand === 'function' && document.execCommand('copy');
    area.remove();
    return Boolean(ok);
  } catch {
    return false;
  }
}

export interface FxHoldToCopyProps {
  children: ReactNode;
  /** What to copy; the visible text when left out. */
  text?: string;
  className?: string;
}

/** A copyable value: Hold to Copy under the switch, plain children otherwise. */
export function FxHoldToCopy({ children, text, className }: FxHoldToCopyProps) {
  const enabled = useFxSetting('h2c') === true;
  if (!enabled) return <>{children}</>;
  return (
    <FxHoldToCopyOn text={text} className={className}>
      {children}
    </FxHoldToCopyOn>
  );
}

type Phase = 'idle' | 'hover' | 'holding' | 'copied' | 'failed';

interface Point {
  x: number;
  y: number;
}

function FxHoldToCopyOn({ children, text, className }: FxHoldToCopyProps) {
  const holdMs = Number(useFxSetting('h2c-time') ?? 0.75) * 1000;
  const copiedMs = Number(useFxSetting('h2c-copied') ?? 1.4) * 1000;
  const reach = Number(useFxSetting('h2c-reach') ?? 8);

  const ref = useRef<HTMLSpanElement>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [at, setAt] = useState<Point>({ x: 0, y: 0 });
  const [touch, setTouch] = useState(false);
  const start = useRef<Point | null>(null);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inside = useRef(false);
  const swallowClick = useRef(false);

  const clearHold = () => {
    if (holdTimer.current) clearTimeout(holdTimer.current);
    holdTimer.current = null;
    start.current = null;
  };

  useEffect(
    () => () => {
      if (holdTimer.current) clearTimeout(holdTimer.current);
      if (doneTimer.current) clearTimeout(doneTimer.current);
    },
    [],
  );

  const finish = useCallback(
    (result: 'copied' | 'failed') => {
      setPhase(result);
      if (doneTimer.current) clearTimeout(doneTimer.current);
      doneTimer.current = setTimeout(() => {
        doneTimer.current = null;
        setPhase(inside.current ? 'hover' : 'idle');
      }, copiedMs);
    },
    [copiedMs],
  );

  const copyNow = useCallback(() => {
    holdTimer.current = null;
    start.current = null;
    swallowClick.current = true;
    const el = ref.current;
    const value = text ?? (el ? fxVisibleText(el) : '');
    void fxCopyText(value).then((ok) => finish(ok ? 'copied' : 'failed'));
  }, [text, finish]);

  const cancel = () => {
    clearHold();
    setPhase((p) => (p === 'holding' ? (inside.current ? 'hover' : 'idle') : p));
  };

  const onPointerEnter = (e: ReactPointerEvent) => {
    inside.current = true;
    setTouch(e.pointerType === 'touch');
    setAt({ x: e.clientX, y: e.clientY });
    if (e.pointerType === 'mouse') setPhase((p) => (p === 'idle' ? 'hover' : p));
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    setAt({ x: e.clientX, y: e.clientY });
    const s = start.current;
    if (s && Math.hypot(e.clientX - s.x, e.clientY - s.y) > FX_H2C_MOVE_CANCEL) cancel();
  };

  const onPointerLeave = () => {
    inside.current = false;
    if (holdTimer.current) cancel();
    setPhase((p) => (p === 'hover' || p === 'holding' ? 'idle' : p));
  };

  const onPointerDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    inside.current = true;
    swallowClick.current = false;
    setTouch(e.pointerType === 'touch');
    setAt({ x: e.clientX, y: e.clientY });
    start.current = { x: e.clientX, y: e.clientY };
    if (doneTimer.current) clearTimeout(doneTimer.current);
    setPhase('holding');
    if (holdTimer.current) clearTimeout(holdTimer.current);
    holdTimer.current = setTimeout(copyNow, holdMs);
  };

  const onPointerUp = (e: ReactPointerEvent) => {
    if (holdTimer.current) cancel();
    if (e.pointerType === 'touch') inside.current = false;
  };

  // The click that ends a hold never reaches a link or row under it.
  const onClickCapture = (e: ReactMouseEvent) => {
    if (!swallowClick.current) return;
    swallowClick.current = false;
    e.preventDefault();
    e.stopPropagation();
  };

  const tipShown = phase !== 'idle';
  const pad = `${reach}px`;

  return (
    <>
      <span
        ref={ref}
        role="presentation"
        data-fx-h2c=""
        data-fx-h2c-phase={phase}
        onPointerEnter={onPointerEnter}
        onPointerMove={onPointerMove}
        onPointerLeave={onPointerLeave}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={cancel}
        onClickCapture={onClickCapture}
        onContextMenu={(e) => {
          if (phase !== 'idle' && phase !== 'hover') e.preventDefault();
        }}
        style={{ padding: pad, margin: `-${pad}` }}
        className={cn(
          'cursor-copy select-none [-webkit-touch-callout:none] [box-decoration-break:clone]',
          className,
        )}
      >
        {children}
      </span>
      {tipShown &&
        typeof document !== 'undefined' &&
        createPortal(<FxCopyTip phase={phase} at={at} touch={touch} />, document.body)}
    </>
  );
}

function FxCopyTip({ phase, at, touch }: { phase: Phase; at: Point; touch: boolean }) {
  // Mouse: 10px right of and 24px above the pointer. Touch: above the finger.
  const left = touch ? at.x : at.x + 10;
  const top = touch ? at.y - 44 : at.y - 24;
  const done = phase === 'copied' || phase === 'failed';
  return (
    <span
      role="status"
      aria-live="polite"
      data-fx-copy-tip={phase}
      className={cn(
        'pointer-events-none fixed z-(--fx-z-tip) flex -translate-y-1/2 items-center',
        touch && '-translate-x-1/2',
      )}
      style={{ left, top }}
    >
      <span data-fx-tool-bg="" className="flex min-h-9 min-w-9 items-center justify-center px-3 py-2">
        <span data-fx-tool-ink="" className="flex items-center text-sm font-medium text-(--fx-ink)">
          {done ? (
            <span className="animate-in fade-in slide-in-from-left-1 duration-(--fx-t-hover) ease-(--fx-ease-out)">
              {phase === 'copied' ? 'Copied' : "Couldn't copy"}
            </span>
          ) : (
            <span className="relative flex size-6 items-center justify-center">
              <Copy aria-hidden="true" className="size-3.5" />
              {phase === 'holding' && (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="absolute inset-0 size-6 -rotate-90">
                  <circle
                    data-fx-h2c-ring=""
                    cx="12"
                    cy="12"
                    r="10.5"
                    pathLength={1}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeDasharray="1"
                  />
                </svg>
              )}
              <span className="sr-only">{phase === 'holding' ? 'Hold to copy' : 'Copy'}</span>
            </span>
          )}
        </span>
      </span>
    </span>
  );
}

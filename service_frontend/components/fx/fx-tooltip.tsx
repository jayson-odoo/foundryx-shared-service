'use client';

/**
 * Hover tooltips under the Foundryx UIUX switch (playbook 0.71.0 "Hover
 * tooltips").
 *
 * - Follows the pointer and never covers what it describes: the box starts at
 *   the pointer and sits on the element's top edge (never lower than 26px
 *   above the pointer); if it does not fit it centres on the pointer, then
 *   moves to its left, and only then goes below.
 * - Solid themed backing (setting "Tooltip background", 92%) with a 6px blur,
 *   hairline edge and soft shadow; wraps at about 280px of text.
 * - Shows after the tooltip delay (0.3 s) and fades in while growing from 60%
 *   (0.15 s); hides on leaving, clicking, scrolling or typing.
 * - Touch: press and hold 0.5 s shows it centred about 40px above the finger;
 *   moving first cancels; letting go after it shows does not press the
 *   button, and it fades about 1.2 s later.
 * - Never shows when it would repeat the words already on the element.
 * - Setting "Styled tooltips" off: the browser's own `title` comes back.
 */
import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
  type SyntheticEvent,
  type PointerEvent as ReactPointerEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useFxSetting } from '@/hooks/use-fx';

const TOUCH_HOLD_MS = 500;
const TOUCH_LINGER_MS = 1200;
const MOVE_CANCEL_PX = 10;
const GAP = 26;
const EDGE = 8;

interface Anchor {
  x: number;
  y: number;
  rect: DOMRect;
  touch: boolean;
}

/** Where the tip goes (pure, so it is unit-tested): see the file header. */
export function placeFxTip(
  anchor: Anchor,
  tip: { width: number; height: number },
  viewport: { width: number; height: number },
): { left: number; top: number } {
  const { x, y, rect, touch } = anchor;
  const fitsX = (left: number) =>
    left >= EDGE && left + tip.width <= viewport.width - EDGE;
  let left: number;
  if (touch) {
    left = x - tip.width / 2;
    if (!fitsX(left)) left = x - tip.width - 16;
    if (!fitsX(left)) left = x + 16;
  } else {
    left = x;
    if (!fitsX(left)) left = x - tip.width / 2;
    if (!fitsX(left)) left = x - tip.width;
  }
  left = Math.min(Math.max(EDGE, left), viewport.width - EDGE - tip.width);

  const clear = touch ? 40 : GAP;
  const large = rect.height > 64;
  const bottom = touch || large ? y - clear : Math.min(rect.top - 2, y - clear);
  let top = bottom - tip.height;
  if (top < EDGE) {
    top = touch || large ? y + clear : Math.max(rect.bottom + 2, y + clear);
  }
  return { left, top };
}

/** The element's words as shown, without parts hidden from everyone (the
 *  focus-only label of an icon action). */
function visibleText(el: Element): string {
  const clone = el.cloneNode(true) as Element;
  clone.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
  return (clone.textContent ?? '').replace(/\s+/g, ' ').trim();
}

interface FxTooltipProps {
  /** The tip's words. Empty renders the child alone. */
  label: string;
  /** One element that accepts pointer handlers (a button). */
  children: ReactElement<Record<string, unknown>>;
}

type Phase = 'hidden' | 'enter' | 'shown' | 'leave';

export function FxTooltip({ label, children }: FxTooltipProps) {
  const styled = useFxSetting('tips') !== false;
  const touchTips = useFxSetting('touch-tips') !== false;
  const delay = Number(useFxSetting('tip-delay') ?? 0.3) * 1000;
  const fade = Number(useFxSetting('tip-fade') ?? 0.15) * 1000;

  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [phase, setPhase] = useState<Phase>('hidden');
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const swallowClick = useRef(false);
  const pendingAnchor = useRef<Anchor | null>(null);

  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const hide = useCallback(() => {
    clear();
    start.current = null;
    setPhase((current) => (current === 'hidden' ? current : 'leave'));
  }, []);

  // After the fade-out the tip leaves the DOM.
  useEffect(() => {
    if (phase !== 'leave') return;
    const t = setTimeout(() => {
      setPhase('hidden');
      setAnchor(null);
      setPos(null);
    }, fade);
    return () => clearTimeout(t);
  }, [phase, fade]);

  useEffect(() => {
    if (phase === 'hidden') return;
    const off = () => hide();
    window.addEventListener('scroll', off, true);
    window.addEventListener('keydown', off, true);
    return () => {
      window.removeEventListener('scroll', off, true);
      window.removeEventListener('keydown', off, true);
    };
  }, [phase, hide]);

  useEffect(() => clear, []);

  useLayoutEffect(() => {
    if (!anchor || phase === 'hidden' || !tipRef.current) return;
    const box = tipRef.current.getBoundingClientRect();
    setPos(
      placeFxTip(
        anchor,
        { width: box.width, height: box.height },
        { width: window.innerWidth, height: window.innerHeight },
      ),
    );
  }, [anchor, phase]);

  // Grow in on the frame after mount.
  useEffect(() => {
    if (phase !== 'enter') return;
    const raf = requestAnimationFrame(() => setPhase('shown'));
    return () => cancelAnimationFrame(raf);
  }, [phase]);

  if (!label || !isValidElement(children)) return children;
  if (!styled) return cloneElement(children, { title: label });

  const repeats = (el: Element) =>
    visibleText(el).toLowerCase() === label.trim().toLowerCase();

  const show = (next: Anchor, el: Element) => {
    if (repeats(el)) return;
    setAnchor(next);
    setPhase('enter');
  };

  const call = (name: string, event: SyntheticEvent) => {
    const own = children.props[name];
    if (typeof own === 'function') own(event);
  };

  const handlers = {
    onPointerEnter: (event: ReactPointerEvent<Element>) => {
      call('onPointerEnter', event);
      if (event.pointerType === 'touch') return;
      const el = event.currentTarget;
      pendingAnchor.current = {
        x: event.clientX,
        y: event.clientY,
        rect: el.getBoundingClientRect(),
        touch: false,
      };
      clear();
      timer.current = setTimeout(() => {
        if (pendingAnchor.current) show(pendingAnchor.current, el);
      }, delay);
    },
    onPointerMove: (event: ReactPointerEvent<Element>) => {
      call('onPointerMove', event);
      if (event.pointerType === 'touch') {
        const s = start.current;
        if (
          s &&
          Math.hypot(event.clientX - s.x, event.clientY - s.y) > MOVE_CANCEL_PX
        )
          hide();
        return;
      }
      const next = {
        x: event.clientX,
        y: event.clientY,
        rect: event.currentTarget.getBoundingClientRect(),
        touch: false,
      };
      pendingAnchor.current = next;
      if (phase === 'enter' || phase === 'shown') setAnchor(next);
    },
    onPointerLeave: (event: ReactPointerEvent<Element>) => {
      call('onPointerLeave', event);
      if (event.pointerType !== 'touch') hide();
    },
    onPointerDown: (event: ReactPointerEvent<Element>) => {
      call('onPointerDown', event);
      if (event.pointerType !== 'touch') {
        hide();
        return;
      }
      if (!touchTips) return;
      const el = event.currentTarget;
      start.current = { x: event.clientX, y: event.clientY };
      const next = {
        x: event.clientX,
        y: event.clientY,
        rect: el.getBoundingClientRect(),
        touch: true,
      };
      clear();
      timer.current = setTimeout(() => {
        swallowClick.current = true;
        show(next, el);
      }, TOUCH_HOLD_MS);
    },
    onPointerUp: (event: ReactPointerEvent<Element>) => {
      call('onPointerUp', event);
      if (event.pointerType !== 'touch') return;
      clear();
      start.current = null;
      if (swallowClick.current) timer.current = setTimeout(hide, TOUCH_LINGER_MS);
    },
    onPointerCancel: (event: ReactPointerEvent<Element>) => {
      call('onPointerCancel', event);
      hide();
    },
    onClickCapture: (event: ReactMouseEvent<Element>) => {
      if (swallowClick.current) {
        swallowClick.current = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      call('onClickCapture', event);
    },
    onContextMenu: (event: ReactMouseEvent<Element>) => {
      if (start.current || swallowClick.current) event.preventDefault();
      call('onContextMenu', event);
    },
  };

  const visible = phase === 'shown' && pos !== null;
  const style: CSSProperties = {
    left: pos?.left ?? -9999,
    top: pos?.top ?? -9999,
    transitionDuration: `${fade}ms`,
    transformOrigin: anchor?.touch ? 'center bottom' : 'left bottom',
  };

  return (
    <>
      {cloneElement(children, handlers)}
      {anchor &&
        phase !== 'hidden' &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            ref={tipRef}
            role="tooltip"
            data-fx-tip=""
            data-state={visible ? 'shown' : 'hidden'}
            style={style}
            className={
              'pointer-events-none fixed z-(--fx-z-tip) w-max max-w-[300px] rounded-(--fx-r-m) border border-(--fx-line) bg-[color-mix(in_srgb,var(--fx-surface)_var(--fx-tip-bg,92%),transparent)] px-2.5 py-1.5 text-sm text-(--fx-ink) shadow-[0_8px_24px_var(--fx-shade)] backdrop-blur-[6px] transition-[opacity,scale] ease-(--fx-ease-spring) ' +
              (visible
                ? 'scale-100 opacity-100'
                : 'scale-[0.6] opacity-0 motion-reduce:scale-100')
            }
          >
            {label}
          </div>,
          document.body,
        )}
    </>
  );
}

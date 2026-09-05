'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';

export interface CursorMenuItem {
  id: string;
  label: string;
  icon?: LucideIcon;
  danger?: boolean;
  separatorBefore?: boolean;
  onSelect: () => void;
}

export interface CursorMenuState {
  x: number;
  y: number;
  items: CursorMenuItem[];
}

/**
 * Cursor-anchored context menu (sprint-3/04b). Radix's ContextMenu doesn't open
 * reliably on a dnd-kit draggable (the pointer sensors swallow the event - same
 * reason the workflow/status canvases use a custom menu). This one opens from an
 * explicit onContextMenu handler, clamps into the viewport, and closes on
 * click-away / Escape / scroll.
 */
export function CursorMenu({
  state,
  onClose,
}: {
  state: CursorMenuState | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: 0, top: 0 });

  useLayoutEffect(() => {
    if (!state || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const pad = 8;
    const left = Math.min(state.x, window.innerWidth - rect.width - pad);
    const top = Math.min(state.y, window.innerHeight - rect.height - pad);
    setPos({ left: Math.max(pad, left), top: Math.max(pad, top) });
  }, [state]);

  useEffect(() => {
    if (!state) return;
    const close = () => onClose();
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('keydown', onKey);
    };
  }, [state, onClose]);

  if (!state || typeof document === 'undefined') return null;

  return createPortal(
    <>
      {/* click-away catcher */}
      <div className="fixed inset-0 z-50" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        ref={ref}
        role="menu"
        style={{ left: pos.left, top: pos.top }}
        className="fixed z-50 min-w-44 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
      >
        {state.items.map((item) => (
          <div key={item.id}>
            {item.separatorBefore && <div className="my-1 h-px bg-border" />}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onClose();
                item.onSelect();
              }}
              className={cn(
                PRESSED_CLASS,
                'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm outline-hidden hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
                item.danger && 'text-destructive hover:bg-destructive/10',
              )}
            >
              {item.icon && <item.icon className="size-4" />}
              {item.label}
            </button>
          </div>
        ))}
      </div>
    </>,
    document.body,
  );
}

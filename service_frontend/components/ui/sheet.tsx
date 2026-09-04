'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';
import { Dialog as SheetPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import { OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';
import { createOutsideInteractionGuard } from '@/components/common/floatingAncestry';
import { surfaceExitTransition, surfaceTransition, useOpenState, useReducedMotion } from '@/lib/motion';

// Mirrors the Root's open state so SheetContent can gate its own
// <AnimatePresence> - see the identical DialogOpenContext in dialog.tsx.
const SheetOpenContext = React.createContext(true);

/**
 * True once the document direction is known to be RTL - a left/right
 * sheet's slide direction has to follow whichever screen edge it actually
 * renders at, which flips under `dir="rtl"` (the CSS `start-0`/`end-0` it is
 * positioned with are logical properties; the slide offset below is a plain
 * `x` and has to be told explicitly).
 */
function useIsRtl(): boolean {
  const [rtl, setRtl] = React.useState(false);
  React.useEffect(() => {
    setRtl(document.documentElement.dir === 'rtl');
  }, []);
  return rtl;
}

/**
 * The slide-only variants a sheet opens/closes with per `side` (AC-DLA-20) -
 * no scale, no fade, matching the pre-spring `slide-in-from-*`/
 * `slide-out-to-*` classes it replaces. Reduced motion drops the slide for a
 * same-frame fade.
 */
function slideVariants(
  prefersReducedMotion: boolean | null,
  side: 'top' | 'bottom' | 'left' | 'right',
  rtl: boolean,
) {
  if (prefersReducedMotion) {
    return { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } };
  }
  const offset: Record<typeof side, { x: string } | { y: string }> = {
    top: { y: '-100%' },
    bottom: { y: '100%' },
    left: { x: rtl ? '100%' : '-100%' },
    right: { x: rtl ? '-100%' : '100%' },
  };
  return { initial: offset[side], animate: { x: 0, y: 0 }, exit: offset[side] };
}

function Sheet({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  modal,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Root>) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  return (
    <SheetOpenContext.Provider value={open}>
      <SheetPrimitive.Root data-slot="sheet" modal={modal ?? true} open={open} onOpenChange={setOpen} {...props} />
    </SheetOpenContext.Provider>
  );
}

function SheetTrigger({ ...props }: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetClose({ ...props }: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />;
}

function SheetPortal({ ...props }: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />;
}

function SheetOverlay({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(OVERLAY_CLASS_STATIC, className)}
      {...props}
    />
  );
}

const sheetVariants = cva(
  // `overflow-y-auto` so a sheet with no SheetBody still reaches its footer.
  // The slide itself is the shared spring below (AC-DLA-20), not a CSS
  // transition.
  'flex flex-col items-strech fixed z-(--z-modal) gap-4 overflow-y-auto bg-background p-6 shadow-lg',
  {
    variants: {
      // A left/right sheet is `h-full`, which already caps it at the
      // viewport; a top/bottom one is sized by its content and needs the
      // explicit cap.
      side: {
        top: 'inset-x-0 top-0 max-h-[90dvh] border-b',
        bottom: 'inset-x-0 bottom-0 max-h-[90dvh] border-t',
        left: 'inset-y-0 start-0 h-full w-3/4 border-e sm:max-w-sm',
        right: 'inset-y-0 end-0 h-full w-3/4 border-s sm:max-w-sm',
      },
    },
    defaultVariants: {
      side: 'right',
    },
  },
);

interface SheetContentProps
  extends React.ComponentProps<typeof SheetPrimitive.Content>,
    VariantProps<typeof sheetVariants> {
  overlay?: boolean;
  close?: boolean;
}

function SheetContent({
  side = 'right',
  overlay = true,
  close = true,
  className,
  children,
  onCloseAutoFocus,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & SheetContentProps) {
  const open = React.useContext(SheetOpenContext);
  const prefersReducedMotion = useReducedMotion();
  const rtl = useIsRtl();
  const transition = surfaceTransition(prefersReducedMotion);
  const exitTransition = surfaceExitTransition(prefersReducedMotion);
  const variants = slideVariants(prefersReducedMotion, side ?? 'right', rtl);
  // T3 fix round 1 finding 8 - the same guardOutsideInteraction/
  // restoreFocusToOpener pair as dialog.tsx (see there for the full
  // rationale); a Sheet is a lightbox surface too and hits the identical
  // trailing-event-from-the-opening-surface + focus-lands-on-body problems.
  const mountedAtRef = React.useRef<number>(0);
  const openerRef = React.useRef<HTMLElement | null>(null);
  const contentRefCallback = React.useCallback((node: HTMLDivElement | null) => {
    if (node) {
      mountedAtRef.current = performance.now();
      const active = document.activeElement;
      if (openerRef.current === null && active instanceof HTMLElement && active !== document.body && !node.contains(active)) {
        openerRef.current = active;
      }
    } else {
      mountedAtRef.current = 0;
    }
  }, []);

  const restoreFocusToOpener = (event: Event) => {
    const opener = openerRef.current;
    openerRef.current = null;
    onCloseAutoFocus?.(event);
    if (event.defaultPrevented) return;
    if (!opener || !opener.isConnected) return;
    event.preventDefault();
    opener.focus();
  };
  // T3 fix round 2 finding 5: factored into `createOutsideInteractionGuard`
  // (`floatingAncestry.ts`) so the guard logic is unit-testable in one place.
  const guardOutsideInteraction = createOutsideInteractionGuard(mountedAtRef);

  return (
    <AnimatePresence>
      {open && (
        <SheetPortal forceMount>
          {overlay && (
            <SheetPrimitive.Overlay asChild forceMount data-slot="sheet-overlay">
              <motion.div
                className={OVERLAY_CLASS_STATIC}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: exitTransition }}
                transition={transition}
              />
            </SheetPrimitive.Overlay>
          )}
          <SheetPrimitive.Content
            ref={contentRefCallback}
            asChild
            forceMount
            data-slot="sheet-content"
            onPointerDownOutside={guardOutsideInteraction}
            onInteractOutside={guardOutsideInteraction}
            onFocusOutside={guardOutsideInteraction}
            onCloseAutoFocus={restoreFocusToOpener}
            {...props}
          >
            <motion.div
              className={cn(sheetVariants({ side }), className)}
              initial={variants.initial}
              animate={variants.animate}
              exit={{ ...variants.exit, transition: exitTransition }}
              transition={transition}
            >
              {children}
              {close && (
                <SheetPrimitive.Close
                  data-slot="sheet-close"
                  className="cursor-pointer absolute end-5 top-4 rounded-sm opacity-60 ring-offset-background transition-opacity hover:opacity-100 focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-secondary"
                >
                  <X className="h-4 w-4" />
                  <span className="sr-only">Close</span>
                </SheetPrimitive.Close>
              )}
            </motion.div>
          </SheetPrimitive.Content>
        </SheetPortal>
      )}
    </AnimatePresence>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-header"
      className={cn('flex flex-col space-y-1 text-center sm:text-start', className)}
      {...props}
    />
  );
}

function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="sheet-body" className={cn('flex-1 min-h-0 overflow-y-auto py-2.5', className)} {...props} />;
}

function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2', className)}
      {...props}
    />
  );
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn('text-base font-semibold leading-tight tracking-normal text-foreground', className)}
      {...props}
    />
  );
}

function SheetDescription({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

export {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetOverlay,
  SheetPortal,
  SheetTitle,
  SheetTrigger,
};

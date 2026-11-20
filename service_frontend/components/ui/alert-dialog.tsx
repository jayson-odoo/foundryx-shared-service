'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { buttonVariants } from '@/components/ui/button';
import { VariantProps } from 'class-variance-authority';
import { AlertDialog as AlertDialogPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import { OVERLAY_CLASS, OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';
import { createOutsideInteractionGuard } from '@/components/common/floatingAncestry';
import {
  surfaceExitTransition,
  surfaceTransition,
  surfaceVariants,
  useOpenState,
  useReducedMotion,
} from '@/lib/motion';

// Mirrors the Root's open state so AlertDialogContent can gate its own
// <AnimatePresence> - see the identical DialogOpenContext in dialog.tsx.
const AlertDialogOpenContext = React.createContext(true);

function AlertDialog({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Root>) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  return (
    <AlertDialogOpenContext.Provider value={open}>
      <AlertDialogPrimitive.Root data-slot="alert-dialog" open={open} onOpenChange={setOpen} {...props} />
    </AlertDialogOpenContext.Provider>
  );
}

function AlertDialogTrigger({ ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Trigger>) {
  return <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />;
}

function AlertDialogPortal({ ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Portal>) {
  return <AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />;
}

// T3 fix round 1 finding 12: T3's spring migration inlined the overlay's
// `motion.div` straight into `AlertDialogContent` and dropped this
// standalone export entirely (it existed pre-spring, mirroring
// `DialogOverlay`). Restored the same way as `DialogOverlay`: `OVERLAY_CLASS`
// (with its own CSS fade), since this export is NOT spring-driven when used
// alone. Zero importers today - kept for API stability.
function AlertDialogOverlay({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Overlay>) {
  return (
    <AlertDialogPrimitive.Overlay data-slot="alert-dialog-overlay" className={cn(OVERLAY_CLASS, className)} {...props} />
  );
}

function AlertDialogContent({
  className,
  children,
  onCloseAutoFocus,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  const open = React.useContext(AlertDialogOpenContext);
  const prefersReducedMotion = useReducedMotion();
  // Same lightbox spring as Dialog - a confirmation is a lightbox too, not a
  // menu, so it opens on the 0.3s response and closes on 0.2s exactly like
  // Dialog/Sheet (AC-DLA-20).
  const base = surfaceVariants(prefersReducedMotion);
  const centerOffset = { x: '-50%', y: '-50%' };
  const variants = {
    initial: { ...base.initial, ...centerOffset },
    animate: { ...base.animate, ...centerOffset },
    exit: { ...base.exit, ...centerOffset },
  };
  const transition = surfaceTransition(prefersReducedMotion, 'lightbox');
  const exitTransition = surfaceExitTransition(prefersReducedMotion);
  // T3 fix round 1 finding 8 - ported from `sorento_crm`/`dialog.tsx` (the
  // AlertDialog equivalent Sorento left as a follow-up; this repo ships it
  // now since the request calls for parity across Dialog/AlertDialog/Sheet).
  // See dialog.tsx's identical block for the full rationale.
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
  // Radix's `AlertDialogContentProps` deliberately OMITS `onPointerDownOutside`/
  // `onInteractOutside` from `DialogContentProps` (confirmed against
  // `@radix-ui/react-alert-dialog`'s own types) - an AlertDialog is never
  // dismissable by an outside click at all, by design (it demands an explicit
  // choice). Only `onFocusOutside` survives that Omit, so this guard is wired
  // to that alone below - still useful for the identical stacked-surface /
  // trailing-event cases `dialog.tsx`'s guard documents. T3 fix round 2
  // finding 5: factored into `createOutsideInteractionGuard`
  // (`floatingAncestry.ts`) so the guard logic is unit-testable in one place.
  const guardOutsideInteraction = createOutsideInteractionGuard(mountedAtRef);

  return (
    <AnimatePresence>
      {open && (
        <AlertDialogPortal forceMount>
          <AlertDialogPrimitive.Overlay asChild forceMount data-slot="alert-dialog-overlay">
            <motion.div
              className={OVERLAY_CLASS_STATIC}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: exitTransition }}
              transition={transition}
            />
          </AlertDialogPrimitive.Overlay>
          <AlertDialogPrimitive.Content
            ref={contentRefCallback}
            asChild
            forceMount
            data-slot="alert-dialog-content"
            onFocusOutside={guardOutsideInteraction}
            onCloseAutoFocus={restoreFocusToOpener}
            {...props}
          >
            <motion.div
              className={cn(
                // `max-h` + `overflow-y-auto`: a long confirmation (a bulk
                // delete listing its rows) otherwise runs off a phone
                // screen with its buttons below the fold. The open/close
                // motion is the spring above, so no `animate-in`/`duration`/
                // `ease` classes here (AC-DLA-20, matches DialogContent).
                'fixed left-[50%] top-[50%] z-(--z-modal) grid max-h-[90dvh] w-full max-w-lg gap-4 overflow-y-auto border bg-background p-6 shadow-lg shadow-black/5 sm:rounded-lg',
                className,
              )}
              initial={variants.initial}
              animate={variants.animate}
              exit={{ ...variants.exit, transition: exitTransition }}
              transition={transition}
            >
              {children}
            </motion.div>
          </AlertDialogPrimitive.Content>
        </AlertDialogPortal>
      )}
    </AnimatePresence>
  );
}

const AlertDialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    data-slot="alert-dialog-header"
    className={cn('flex flex-col space-y-2 text-center sm:text-left', className)}
    {...props}
  />
);

const AlertDialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    data-slot="alert-dialog-footer"
    className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2.5', className)}
    {...props}
  />
);

function AlertDialogTitle({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn('text-lg font-semibold leading-tight tracking-normal', className)}
      {...props}
    />
  );
}

function AlertDialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

function AlertDialogAction({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Action> & VariantProps<typeof buttonVariants>) {
  return (
    <AlertDialogPrimitive.Action
      data-slot="alert-dialog-action"
      className={cn(buttonVariants({ variant }), className)}
      {...props}
    />
  );
}

function AlertDialogCancel({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
  return (
    <AlertDialogPrimitive.Cancel
      data-slot="alert-dialog-cancel"
      className={cn(buttonVariants({ variant: 'outline' }), 'mt-2 sm:mt-0', className)}
      {...props}
    />
  );
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
};

'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import { OVERLAY_CLASS, OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';
import { focusIsInsideFloating } from '@/components/common/floatingAncestry';
import {
  REDUCED_MOTION_TRANSITION,
  surfaceExitTransition,
  surfaceTransition,
  surfaceVariants,
  useOpenState,
  useReducedMotion,
} from '@/lib/motion';

const dialogContentVariants = cva(
  // `overflow-y-auto` + a bounded `max-h` make EVERY modal scrollable - tall
  // content otherwise overflows the viewport on mobile with no way to reach
  // the submit button. The open/close motion is the spring below (AC-DLA-20),
  // so no `animate-in`/`duration`/`ease` classes here.
  'flex flex-col fixed outline-0 z-(--z-modal) border border-border bg-background p-6 shadow-lg shadow-black/5 overflow-y-auto sm:rounded-lg',
  {
    variants: {
      variant: {
        default: 'left-[50%] top-[50%] max-h-[90dvh] max-w-lg w-full',
        fullscreen: 'inset-5',
      },
      // T3 fix round 1 finding 1 (BLOCKER): centering used to be folded
      // straight into the animated `motion.div` transform (`centerOffset`
      // below), which meant a consumer's OWN `lg:top-[15%] lg:translate-y-0`
      // override (search-dialog.tsx) got silently clobbered the moment the
      // spring ticked - motion owns the whole inline `transform`, so a
      // Tailwind `translate-*` utility on the same node never wins. `top`
      // makes that offset a first-class variant instead: `centerOffset`
      // below reads it and only ever contributes `y: '-50%'` for `center`.
      position: {
        center: '',
        top: 'top-[15%]',
      },
    },
    defaultVariants: {
      variant: 'default',
      position: 'center',
    },
  },
);

// Mirrors the Root's open state so DialogContent can gate its own
// <AnimatePresence> - Radix's Presence unmounts on a CSS animation it can
// detect, which a JS spring is not (see lib/motion.ts useOpenState).
const DialogOpenContext = React.createContext(true);

function Dialog({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  modal,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  return (
    <DialogOpenContext.Provider value={open}>
      <DialogPrimitive.Root data-slot="dialog" modal={modal ?? true} open={open} onOpenChange={setOpen} {...props} />
    </DialogOpenContext.Provider>
  );
}

function DialogTrigger({ ...props }: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal({ ...props }: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose({ ...props }: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

// T3 fix round 1 finding 12: this standalone export is NOT the overlay
// `DialogContent` itself renders (that one is spring-driven inline,
// `OVERLAY_CLASS_STATIC` - see below) - it is for a caller that mounts
// `<DialogOverlay>` on its own, outside `DialogContent`'s own
// `<AnimatePresence>`. `OVERLAY_CLASS_STATIC` on its own has no fade at all;
// a standalone overlay needs `OVERLAY_CLASS`'s `animate-in`/`animate-out`
// CSS fade to not just hard-pop in and out. Zero importers today - kept for
// API stability (a future caller reaching for `DialogOverlay` directly gets
// a scrim that actually animates).
function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return <DialogPrimitive.Overlay data-slot="dialog-overlay" className={cn(OVERLAY_CLASS, className)} {...props} />;
}

function hasDialogTitleInChildren(children: React.ReactNode): boolean {
  const check = (nodes: React.ReactNode): boolean => {
    return React.Children.toArray(nodes).some((child) => {
      if (!React.isValidElement(child)) return false;
      if (child.type === DialogTitle) return true;
      const grandChildren = (child.props as { children?: React.ReactNode })?.children;
      if (grandChildren !== undefined) return check(grandChildren);
      return false;
    });
  };
  return check(children);
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  overlay = true,
  variant,
  position,
  onCloseAutoFocus,
  motion: motionEnabled = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> &
  VariantProps<typeof dialogContentVariants> & {
    showCloseButton?: boolean;
    overlay?: boolean;
    /**
     * A keyboard-triggered surface never animates (AC-DLA-22): `motion={false}`
     * drops the scale entirely, so the panel is simply THERE on the frame
     * after the keydown and gone the frame Escape/a selection fires - no
     * spring to interrupt, no exit to sit through. The scrim still fades,
     * just on a plain `--duration-fast` tween instead of the shared spring.
     */
    motion?: boolean;
  }) {
  const open = React.useContext(DialogOpenContext);
  const prefersReducedMotion = useReducedMotion();
  // Dialog positions `variant="default"` with `left-50%/top-50%` (or, for
  // `position="top"`, `top-[15%]` - see `dialogContentVariants`) + a
  // `translate` to center it; that translate has to travel along with the
  // animated scale/opacity below (motion owns the element's whole
  // `transform`, so a separate Tailwind `translate-*` class would be
  // silently overwritten the moment the spring ticks - T3 fix round 1
  // BLOCKER 1, this is exactly what broke the header Search dialog when
  // `search-dialog.tsx`'s own `lg:translate-y-0` stopped working). `top`
  // only needs the horizontal `-50%` - its vertical position comes entirely
  // from the `top-[15%]` CSS, not a translate. `fullscreen` uses `inset-5`
  // and needs no offset at all.
  const centerOffset =
    variant === 'fullscreen' ? {} : position === 'top' ? { x: '-50%', y: 0 } : { x: '-50%', y: '-50%' };
  const base = surfaceVariants(prefersReducedMotion);
  const variants = motionEnabled
    ? {
        initial: { ...base.initial, ...centerOffset },
        animate: { ...base.animate, ...centerOffset },
        exit: { ...base.exit, ...centerOffset },
      }
    : {
        // No scale and no entry fade: the panel is simply THERE on the frame
        // after the keydown.
        initial: { opacity: 1, ...centerOffset },
        animate: { opacity: 1, ...centerOffset },
        exit: { opacity: 0, ...centerOffset },
      };
  const transition = motionEnabled ? surfaceTransition(prefersReducedMotion) : { duration: 0 };
  const exitTransition = motionEnabled ? surfaceExitTransition(prefersReducedMotion) : { duration: 0 };
  // 0.15s = `--duration-fast` (css/config.reui.css). The scrim is not what a
  // keyboard shortcut is asking to see, so it keeps a quick tween rather than
  // going fully static like the content it sits behind - except for a reader
  // who asked for less motion, who gets the same same-frame change every
  // other surface collapses to.
  const overlayTransition = motionEnabled
    ? transition
    : prefersReducedMotion
      ? REDUCED_MOTION_TRANSITION
      : { duration: 0.15 };
  const needsFallbackTitle = !hasDialogTitleInChildren(children);
  // T3 fix round 1 finding 8 - ported from `sorento_crm` `dialog.tsx`.
  //
  // Track the moment the actual Content DOM node attaches (i.e. the moment
  // the dialog truly opens). We can't use mount of this React component
  // because Radix evaluates `<DialogContent>` even while the dialog is
  // closed; only the underlying DialogPrimitive.Content DOM node toggles
  // with the open state. The grace window below ignores the trailing
  // pointer/focus event from a DropdownMenu / Popover / Select / ContextMenu
  // item that just opened this dialog - those surfaces unmount during the
  // same click cycle and their last event would otherwise land outside the
  // freshly-opened dialog and instantly close it.
  const mountedAtRef = React.useRef<number>(0);
  // Where the keyboard was when this dialog opened.
  //
  // Radix hands focus back to its own DialogTrigger, and this product almost
  // never uses one - a plain button flips state elsewhere, so Radix has no
  // trigger to return to and focus lands on <body> - after Escape the
  // keyboard user is at the top of the document, having lost their place in
  // the list they were working in. Captured in the ref callback because
  // refs attach before Radix's focus effect runs, so this still sees the
  // opener rather than the dialog.
  const openerRef = React.useRef<HTMLElement | null>(null);
  const contentRefCallback = React.useCallback((node: HTMLDivElement | null) => {
    if (node) {
      mountedAtRef.current = performance.now();
      // Capture ONCE per open, and never something inside the dialog.
      //
      // Radix composes this ref, so React detaches and re-attaches it on
      // every render of an open dialog. By the second attach the focus is
      // already on the first control INSIDE the content, and capturing that
      // overwrote the opener with a button that leaves the DOM a moment
      // later - the restore then found a disconnected node and silently
      // gave up, which is exactly the "focus lands on body" symptom this
      // guards against.
      const active = document.activeElement;
      if (openerRef.current === null && active instanceof HTMLElement && active !== document.body && !node.contains(active)) {
        openerRef.current = active;
      }
    } else {
      mountedAtRef.current = 0;
    }
  }, []);

  const restoreFocusToOpener = (event: Event) => {
    // Released FIRST, before anything can return early. This open is over
    // either way, and a held opener makes the capture guard skip the next
    // one - so the dialog after a caller-handled close would hand focus
    // back to the button that opened the dialog before it.
    const opener = openerRef.current;
    openerRef.current = null;

    // The caller decides next; if it took over, leave focus alone.
    onCloseAutoFocus?.(event);
    if (event.defaultPrevented) return;

    // Gone from the DOM - the row that opened this dialog was just deleted -
    // so let Radix do whatever it would have done.
    if (!opener || !opener.isConnected) return;

    // Where a DialogTrigger WAS used, the opener is that trigger, so this
    // lands in the same place Radix would have.
    event.preventDefault();
    opener.focus();
  };
  // Radix wraps these in a CustomEvent whose `target` is the DialogContent
  // itself. The actual click/pointer/focus target is on
  // `event.detail.originalEvent.target`.
  const guardOutsideInteraction = (event: Event) => {
    const detail = (event as CustomEvent<{ originalEvent?: Event }>).detail;
    const original = detail?.originalEvent;
    const target = (original?.target ?? event.target) as Element | null;
    // Ignore the trailing pointer/focus event from the Radix surface that
    // OPENED this dialog (dropdown menu / popover / select / context menu).
    // Those surfaces are unmounting during the same tick the dialog mounts;
    // their event would otherwise be misread as an outside click.
    //
    // Also ignore interactions that land inside ANOTHER dialog stacked above
    // this one. Nested dialogs are portaled as React siblings (not DOM/React
    // descendants), so Radix reads any click in the child dialog as
    // "outside" the parent and would dismiss the parent - closing a stacked
    // dialog must be explicit, never a side effect of the one beneath it.
    if (focusIsInsideFloating(target)) {
      event.preventDefault();
      return;
    }
    // Same trailing-event problem when the closing surface was already
    // unmounted by the time the event fires - target lands on body/html.
    // Suppress any outside interaction within a short grace window after
    // mount; this is well under the click-to-real-outside-click latency.
    if (mountedAtRef.current && performance.now() - mountedAtRef.current < 300) {
      event.preventDefault();
      return;
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <DialogPortal forceMount>
          {overlay && (
            <DialogPrimitive.Overlay asChild forceMount data-slot="dialog-overlay">
              <motion.div
                className={OVERLAY_CLASS_STATIC}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: overlayTransition }}
                transition={overlayTransition}
              />
            </DialogPrimitive.Overlay>
          )}
          <DialogPrimitive.Content
            ref={contentRefCallback}
            asChild
            forceMount
            data-slot="dialog-content"
            data-motion={motionEnabled ? undefined : 'off'}
            onPointerDownOutside={guardOutsideInteraction}
            onInteractOutside={guardOutsideInteraction}
            onFocusOutside={guardOutsideInteraction}
            onCloseAutoFocus={restoreFocusToOpener}
            {...props}
          >
            <motion.div
              className={cn(dialogContentVariants({ variant, position }), className)}
              initial={variants.initial}
              animate={variants.animate}
              exit={{ ...variants.exit, transition: exitTransition }}
              transition={transition}
            >
              {needsFallbackTitle ? (
                <DialogPrimitive.Title className="sr-only">Dialog</DialogPrimitive.Title>
              ) : null}
              {children}
              {showCloseButton && (
                // No `outline-0` / `focus:outline-hidden` - both would
                // defeat the global `*:focus-visible` ring unconditionally.
                <DialogClose className="cursor-pointer absolute end-5 top-5 rounded-sm opacity-60 ring-offset-background transition-opacity hover:opacity-100 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
                  <X className="size-4" />
                  <span className="sr-only">Close</span>
                </DialogClose>
              )}
            </motion.div>
          </DialogPrimitive.Content>
        </DialogPortal>
      )}
    </AnimatePresence>
  );
}

export default DialogContent;

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    data-slot="dialog-header"
    className={cn('flex flex-col space-y-1 text-center sm:text-start mb-5', className)}
    {...props}
  />
);

const DialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    data-slot="dialog-footer"
    className={cn('flex flex-col-reverse sm:flex-row sm:justify-end pt-5 sm:space-x-2.5', className)}
    {...props}
  />
);

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn('text-lg font-semibold leading-tight tracking-normal', className)}
      {...props}
    />
  );
}

const DialogBody = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-slot="dialog-body" className={cn('grow', className)} {...props} />
);

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
};

'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import { OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';
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
    },
    defaultVariants: {
      variant: 'default',
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

function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(OVERLAY_CLASS_STATIC, className)}
      {...props}
    />
  );
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
  // Dialog positions `variant="default"` with `left-50%/top-50%` + a
  // `translate(-50%,-50%)` to center it; that translate has to travel along
  // with the animated scale/opacity below (motion owns the element's whole
  // `transform`, so a separate Tailwind `translate-*` class would be
  // silently overwritten the moment the spring ticks). `fullscreen` uses
  // `inset-5` instead and needs no offset.
  const centerOffset = variant === 'fullscreen' ? {} : { x: '-50%', y: '-50%' };
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
            asChild
            forceMount
            data-slot="dialog-content"
            data-motion={motionEnabled ? undefined : 'off'}
            {...props}
          >
            <motion.div
              className={cn(dialogContentVariants({ variant }), className)}
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

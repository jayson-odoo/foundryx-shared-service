'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { buttonVariants } from '@/components/ui/button';
import { VariantProps } from 'class-variance-authority';
import { AlertDialog as AlertDialogPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import { OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';
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

function AlertDialogContent({
  className,
  children,
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
          <AlertDialogPrimitive.Content asChild forceMount data-slot="alert-dialog-content" {...props}>
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
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
};

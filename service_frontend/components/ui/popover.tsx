'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Popover as PopoverPrimitive } from 'radix-ui';
import { AnimatePresence, motion } from 'motion/react';
import {
  surfaceExitTransition,
  surfaceTransition,
  surfaceVariants,
  useOpenState,
  useReducedMotion,
} from '@/lib/motion';

// Mirrors the Root's open state so PopoverContent can gate its own
// <AnimatePresence> - see the identical DialogOpenContext in dialog.tsx.
const PopoverOpenContext = React.createContext(true);

function Popover({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  return (
    <PopoverOpenContext.Provider value={open}>
      <PopoverPrimitive.Root data-slot="popover" open={open} onOpenChange={setOpen} {...props} />
    </PopoverOpenContext.Provider>
  );
}

function PopoverTrigger({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />;
}

function PopoverContent({
  className,
  align = 'center',
  sideOffset = 4,
  children,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  const open = React.useContext(PopoverOpenContext);
  const prefersReducedMotion = useReducedMotion();
  const variants = surfaceVariants(prefersReducedMotion);
  const transition = surfaceTransition(prefersReducedMotion, 'menu');
  const exitTransition = surfaceExitTransition(prefersReducedMotion);

  // `PopoverPrimitive.Content` positions itself with an inline `transform`
  // (Radix Popper/floating-ui) that a motion.div rendered `asChild` would
  // immediately overwrite the moment the spring ticks (both want the same
  // CSS property on the same node). The spring instead animates an INNER
  // div, so Content's own positioning transform is left alone (AC-DLA-20,
  // AC-DLA-21).
  //
  // Radix sets `--radix-popover-content-transform-origin` as an inline
  // style on `Content` itself; the inner motion.div reads it via CSS
  // custom-property inheritance, which is also where the actual `scale`
  // animation runs, so the origin has to live there too.
  return (
    <AnimatePresence>
      {open && (
        <PopoverPrimitive.Portal forceMount>
          <PopoverPrimitive.Content
            forceMount
            data-slot="popover-content"
            align={align}
            sideOffset={sideOffset}
            className="z-(--z-modal) outline-hidden"
            {...props}
          >
            <motion.div
              className={cn(
                'w-72 rounded-md border border-border bg-popover p-4 text-popover-foreground shadow-md shadow-black/5 origin-(--radix-popover-content-transform-origin)',
                className,
              )}
              initial={variants.initial}
              animate={variants.animate}
              exit={{ ...variants.exit, transition: exitTransition }}
              transition={transition}
            >
              {children}
            </motion.div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      )}
    </AnimatePresence>
  );
}

export { Popover, PopoverContent, PopoverTrigger };

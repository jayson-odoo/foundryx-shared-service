'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import * as HoverCardPrimitive from '@radix-ui/react-hover-card';
import { AnimatePresence, motion } from 'motion/react';
import {
  surfaceExitTransition,
  surfaceTransition,
  surfaceVariants,
  useOpenState,
  useReducedMotion,
} from '@/lib/motion';

// Mirrors the Root's open state so HoverCardContent can gate its own
// <AnimatePresence> - see the identical DialogOpenContext in dialog.tsx.
const HoverCardOpenContext = React.createContext(true);

function HoverCard({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof HoverCardPrimitive.Root>) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  return (
    <HoverCardOpenContext.Provider value={open}>
      <HoverCardPrimitive.Root data-slot="hover-card" open={open} onOpenChange={setOpen} {...props} />
    </HoverCardOpenContext.Provider>
  );
}

function HoverCardTrigger({ ...props }: React.ComponentProps<typeof HoverCardPrimitive.Trigger>) {
  return <HoverCardPrimitive.Trigger data-slot="hover-card-trigger" {...props} />;
}

function HoverCardContent({
  className,
  children,
  align = 'center',
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof HoverCardPrimitive.Content>) {
  const open = React.useContext(HoverCardOpenContext);
  const prefersReducedMotion = useReducedMotion();
  const variants = surfaceVariants(prefersReducedMotion);
  const transition = surfaceTransition(prefersReducedMotion, 'menu');
  const exitTransition = surfaceExitTransition(prefersReducedMotion);

  // Same split as PopoverContent/DropdownMenuContent: Radix Popper owns
  // Content's own positioning transform, so the spring animates an inner
  // div instead.
  return (
    <AnimatePresence>
      {open && (
        <HoverCardPrimitive.Portal forceMount data-slot="hover-card-portal">
          <HoverCardPrimitive.Content
            forceMount
            data-slot="hover-card-content"
            align={align}
            sideOffset={sideOffset}
            className="z-(--z-modal) outline-hidden"
            {...props}
          >
            <motion.div
              className={cn(
                'bg-popover text-popover-foreground w-64 origin-(--radix-hover-card-content-transform-origin) rounded-md border p-4 shadow-md',
                className,
              )}
              initial={variants.initial}
              animate={variants.animate}
              exit={{ ...variants.exit, transition: exitTransition }}
              transition={transition}
            >
              {children}
            </motion.div>
          </HoverCardPrimitive.Content>
        </HoverCardPrimitive.Portal>
      )}
    </AnimatePresence>
  );
}

export { HoverCard, HoverCardTrigger, HoverCardContent };

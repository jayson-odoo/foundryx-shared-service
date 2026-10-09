'use client';

import * as React from 'react';
import { isValidElement, ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { cva, VariantProps } from 'class-variance-authority';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { Select as SelectPrimitive } from 'radix-ui';

// Create a Context for `indicatorPosition` and `indicator` control
const SelectContext = React.createContext<{
  indicatorPosition: 'left' | 'right';
  indicatorVisibility: boolean;
  indicator: ReactNode;
}>({ indicatorPosition: 'left', indicator: null, indicatorVisibility: true });

// Root Component
//
// Unlike Dialog/Sheet/Popover/DropdownMenu/ContextMenu/HoverCard, Select is
// NOT wrapped in `useOpenState` here: Radix Select's own `Content` has no
// `forceMount` escape hatch (see SelectContent below), so there is no exit
// frame an `<AnimatePresence>` gate could ever animate - threading a
// mirrored open state through the Root would be dead plumbing with nothing
// downstream to consume it.
const Select = ({
  indicatorPosition = 'left',
  indicatorVisibility = true,
  indicator,
  ...props
}: {
  indicatorPosition?: 'left' | 'right';
  indicatorVisibility?: boolean;
  indicator?: ReactNode;
} & React.ComponentProps<typeof SelectPrimitive.Root>) => {
  return (
    <SelectContext.Provider value={{ indicatorPosition, indicatorVisibility, indicator }}>
      <SelectPrimitive.Root {...props} />
    </SelectContext.Provider>
  );
};

function SelectGroup({ ...props }: React.ComponentProps<typeof SelectPrimitive.Group>) {
  return <SelectPrimitive.Group data-slot="select-group" {...props} />;
}

function SelectValue({ ...props }: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />;
}

// Define size variants for SelectTrigger
const selectTriggerVariants = cva(
  `
    flex bg-background w-full items-center justify-between outline-none border border-input shadow-xs shadow-black/5 transition-shadow 
    text-foreground data-placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] 
    focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 
    aria-invalid:border-destructive/60 aria-invalid:ring-destructive/10 dark:aria-invalid:border-destructive dark:aria-invalid:ring-destructive/20
    [[data-invalid=true]_&]:border-destructive/60 [[data-invalid=true]_&]:ring-destructive/10  dark:[[data-invalid=true]_&]:border-destructive dark:[[data-invalid=true]_&]:ring-destructive/20
  `,
  {
    variants: {
      size: {
        sm: 'h-7 px-2.5 text-xs gap-1 rounded-md',
        md: 'h-8.5 px-3 text-[0.8125rem] leading-(--text-sm--line-height) gap-1 rounded-md',
        lg: 'h-10 px-4 text-sm gap-1.5 rounded-md',
      },
    },
    defaultVariants: {
      size: 'md',
    },
  },
);

export interface SelectTriggerProps
  extends React.ComponentProps<typeof SelectPrimitive.Trigger>,
    VariantProps<typeof selectTriggerVariants> {}

function SelectTrigger({ className, children, size, ...props }: SelectTriggerProps) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(selectTriggerVariants({ size }), className)}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="h-4 w-4 opacity-60 -me-0.5" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

function SelectScrollUpButton({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.ScrollUpButton>) {
  return (
    <SelectPrimitive.ScrollUpButton
      data-slot="select-scroll-up-button"
      className={cn('flex cursor-default items-center justify-center py-1', className)}
      {...props}
    >
      <ChevronUp className="h-4 w-4" />
    </SelectPrimitive.ScrollUpButton>
  );
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownButton>) {
  return (
    <SelectPrimitive.ScrollDownButton
      data-slot="select-scroll-down-button"
      className={cn('flex cursor-default items-center justify-center py-1', className)}
      {...props}
    >
      <ChevronDown className="h-4 w-4" />
    </SelectPrimitive.ScrollDownButton>
  );
}

function SelectContent({
  className,
  children,
  position = 'popper',
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  // Radix Select's `Content` has no `forceMount` escape hatch (unlike
  // Dialog/Popover/DropdownMenu/HoverCard/ContextMenu/Menubar's own Content
  // primitives) - it fully unmounts the instant the Root closes, so there is
  // no exit frame an `<AnimatePresence>` could ever gate. T3 fix round 1
  // finding 7: a ONE-SIDED spring (390ms in, instant out) reads as two
  // different close behaviours next to a Menubar/DropdownMenu open right
  // beside it - the honest simplification, matching `MenubarContent` (see
  // menubar.tsx), is a SYMMETRIC CSS opacity fade instead: both sides run
  // the same `--duration-fast` tween via Radix's own `data-state`
  // (`animate-out` never actually gets to finish before unmount either, but
  // it declares the same intent both ways rather than favouring open).
  // No zoom - `origin-(--radix-select-content-transform-origin)` stays for
  // whichever future entrance needs it, but a fade needs no explicit origin.
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        className={cn(
          'relative z-(--z-modal) max-h-96 min-w-[8rem]',
          'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 duration-(--duration-fast) ease-(--ease-standard)',
          position === 'popper' &&
            'data-[side=bottom]:translate-y-1.5 data-[side=left]:-translate-x-1.5 data-[side=right]:translate-x-1.5 data-[side=top]:-translate-y-1.5',
        )}
        position={position}
        {...props}
      >
        <div
          className={cn(
            'overflow-hidden rounded-md border border-border bg-popover shadow-md shadow-black/5 text-secondary-foreground origin-(--radix-select-content-transform-origin)',
            className,
          )}
        >
          <SelectScrollUpButton />
          <SelectPrimitive.Viewport
            className={cn(
              'p-1.5',
              position === 'popper' &&
                'h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]',
            )}
          >
            {children}
          </SelectPrimitive.Viewport>
          <SelectScrollDownButton />
        </div>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

function SelectLabel({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return (
    <SelectPrimitive.Label
      data-slot="select-label"
      className={cn('py-1.5 ps-8 pe-2 text-xs text-muted-foreground font-medium', className)}
      {...props}
    />
  );
}

function SelectItem({ className, children, ...props }: React.ComponentProps<typeof SelectPrimitive.Item>) {
  const { indicatorPosition, indicatorVisibility, indicator } = React.useContext(SelectContext);

  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        'relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 text-sm outline-hidden text-foreground hover:bg-accent focus:bg-accent data-disabled:pointer-events-none data-disabled:opacity-50',
        indicatorPosition === 'left' ? 'ps-8 pe-2' : 'pe-8 ps-2',
        className,
      )}
      {...props}
    >
      {indicatorVisibility &&
        (indicator && isValidElement(indicator) ? (
          indicator
        ) : (
          <span
            className={cn(
              'absolute flex h-3.5 w-3.5 items-center justify-center',
              indicatorPosition === 'left' ? 'start-2' : 'end-2',
            )}
          >
            <SelectPrimitive.ItemIndicator>
              <Check className="h-4 w-4 text-primary" />
            </SelectPrimitive.ItemIndicator>
          </span>
        ))}
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

function SelectIndicator({
  children,
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ItemIndicator>) {
  const { indicatorPosition } = React.useContext(SelectContext);

  return (
    <span
      data-slot="select-indicator"
      className={cn(
        'absolute flex top-1/2 -translate-y-1/2 items-center justify-center',
        indicatorPosition === 'left' ? 'start-2' : 'end-2',
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemIndicator>{children}</SelectPrimitive.ItemIndicator>
    </span>
  );
}

function SelectSeparator({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Separator>) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn('-mx-1.5 my-1.5 h-px bg-border', className)}
      {...props}
    />
  );
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectIndicator,
  SelectItem,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
};

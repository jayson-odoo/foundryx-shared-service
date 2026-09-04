'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { Tabs as TabsPrimitive } from 'radix-ui';
import { useHorizontalOverflow } from '@/hooks/use-horizontal-overflow';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';

// Variants for TabsList
const tabsListVariants = cva(
  // The list owns its scroller (AC-DLA-12): without one, a long strip widens
  // the page instead of scrolling. The scrollbar is hidden because it would
  // sit on top of the tab labels; a sibling always-mounted fade overlay (see
  // `TabsList` below, same solution as the DataGrid scroller, AC-DLA-14 fix
  // round 1) marks the right edge instead of a toggled `mask-image`, which
  // switches abruptly with no transition.
  'flex items-center shrink-0 min-w-0 max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
  {
    variants: {
      variant: {
        default: 'bg-accent p-1',
        button: '',
        line: 'border-b border-border',
      },
      shape: {
        default: '',
        pill: '',
      },
      size: {
        lg: 'gap-2.5',
        md: 'gap-2',
        sm: 'gap-1.5',
        xs: 'gap-1',
      },
    },
    compoundVariants: [
      { variant: 'default', size: 'lg', className: 'p-1.5 gap-2.5' },
      { variant: 'default', size: 'md', className: 'p-1 gap-2' },
      { variant: 'default', size: 'sm', className: 'p-1 gap-1.5' },
      { variant: 'default', size: 'xs', className: 'p-1 gap-1' },

      {
        variant: 'default',
        shape: 'default',
        size: 'lg',
        className: 'rounded-lg',
      },
      {
        variant: 'default',
        shape: 'default',
        size: 'md',
        className: 'rounded-lg',
      },
      {
        variant: 'default',
        shape: 'default',
        size: 'sm',
        className: 'rounded-md',
      },
      {
        variant: 'default',
        shape: 'default',
        size: 'xs',
        className: 'rounded-md',
      },

      { variant: 'line', size: 'lg', className: 'gap-9' },
      { variant: 'line', size: 'md', className: 'gap-8' },
      { variant: 'line', size: 'sm', className: 'gap-4' },
      { variant: 'line', size: 'xs', className: 'gap-4' },

      {
        variant: 'default',
        shape: 'pill',
        className: 'rounded-full [&_[role=tab]]:rounded-full',
      },
      {
        variant: 'button',
        shape: 'pill',
        className: 'rounded-full [&_[role=tab]]:rounded-full',
      },
    ],
    defaultVariants: {
      // AC-DLA-12: every tab strip is an underline unless a caller pins
      // `variant="default"` (the segmented two/three-option keepers - see
      // `components/ui/tabs.inventory.test.ts`).
      variant: 'line',
      size: 'md',
    },
  },
);

// Variants for TabsTrigger
const tabsTriggerVariants = cva(
  // Inset focus ring, zero offset (fix round 1): the trigger sits inside
  // TabsList's own `overflow-x-auto` scroller, which clips anything an
  // OUTER ring/offset would draw past the trigger's own box - an inset ring
  // needs no room outside it.
  PRESSED_CLASS +
    ' shrink-0 cursor-pointer whitespace-nowrap inline-flex justify-center items-center font-medium focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-0 disabled:pointer-events-none disabled:opacity-50 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:shrink-0 [&_svg]:text-muted-foreground [&:hover_svg]:text-primary [&[data-state=active]_svg]:text-primary',
  {
    variants: {
      variant: {
        default:
          'text-muted-foreground data-[state=active]:bg-background hover:text-foreground data-[state=active]:text-foreground data-[state=active]:shadow-xs data-[state=active]:shadow-black/5',
        button:
          'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-0 rounded-lg text-accent-foreground hover:text-foreground data-[state=active]:bg-accent data-[state=active]:text-foreground',
        line: 'border-b-2 text-muted-foreground border-transparent data-[state=active]:border-primary hover:text-primary data-[state=active]:text-primary data-[state=active]:border-primary data-[state=active]:text-primary',
      },
      size: {
        lg: 'gap-2.5 [&_svg]:size-5 text-sm',
        md: 'gap-2 [&_svg]:size-4 text-sm',
        sm: 'gap-1.5 [&_svg]:size-3.5 text-xs',
        xs: 'gap-1 [&_svg]:size-3.5 text-xs',
      },
    },
    compoundVariants: [
      { variant: 'default', size: 'lg', className: 'py-2.5 px-4 rounded-md' },
      { variant: 'default', size: 'md', className: 'py-1.5 px-3 rounded-md' },
      { variant: 'default', size: 'sm', className: 'py-1.5 px-2.5 rounded-sm' },
      { variant: 'default', size: 'xs', className: 'py-1 px-2 rounded-sm' },

      { variant: 'button', size: 'lg', className: 'py-3 px-4 rounded-lg' },
      { variant: 'button', size: 'md', className: 'py-2.5 px-3 rounded-lg' },
      { variant: 'button', size: 'sm', className: 'py-2 px-2.5 rounded-md' },
      { variant: 'button', size: 'xs', className: 'py-1.5 px-2 rounded-md' },

      { variant: 'line', size: 'lg', className: 'py-3' },
      { variant: 'line', size: 'md', className: 'py-2.5' },
      { variant: 'line', size: 'sm', className: 'py-2' },
      { variant: 'line', size: 'xs', className: 'py-1.5' },
    ],
    defaultVariants: {
      variant: 'line',
      size: 'md',
    },
  },
);

// Variants for TabsContent
const tabsContentVariants = cva(
  'mt-2.5 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
  {
    variants: {
      variant: {
        default: '',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

// Context
type TabsContextType = {
  variant?: 'default' | 'button' | 'line';
  size?: 'lg' | 'sm' | 'xs' | 'md';
};
const TabsContext = React.createContext<TabsContextType>({
  variant: 'line',
  size: 'md',
});

// Components
function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('', className)} {...props} />;
}

function TabsList({
  className,
  variant = 'line',
  shape = 'default',
  size = 'md',
  ref: callerRef,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  const { ref: scrollerRef, isFading } = useHorizontalOverflow<HTMLDivElement>();

  // The list needs its own ref to measure the overflow, but it is not
  // entitled to the caller's - placing ours after {...props} silently drops
  // one.
  const mergedRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      scrollerRef.current = node;
      if (typeof callerRef === 'function') callerRef(node);
      else if (callerRef) (callerRef as React.RefObject<HTMLDivElement | null>).current = node;
    },
    [scrollerRef, callerRef],
  );

  return (
    <TabsContext.Provider value={{ variant: variant || 'line', size: size || 'md' }}>
      <div className="relative min-w-0 max-w-full">
        <TabsPrimitive.List
          data-slot="tabs-list"
          className={cn(tabsListVariants({ variant, shape, size }), className)}
          {...props}
          ref={mergedRef}
        />
        {/* Always mounted (AC-DLA-14 fix round 1), same solution as the
            DataGrid's right-edge fade - opacity only, never mount/unmount or
            mask-image toggling. */}
        <div
          aria-hidden="true"
          data-slot="tabs-fade"
          data-fade={isFading}
          className="pointer-events-none absolute inset-y-0 end-0 w-6 bg-gradient-to-l from-background to-transparent opacity-0 transition-opacity duration-(--duration-fast) data-[fade=true]:opacity-100"
        />
      </div>
    </TabsContext.Provider>
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  const { variant, size } = React.useContext(TabsContext);

  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(tabsTriggerVariants({ variant, size }), className)}
      {...props}
    />
  );
}

function TabsContent({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content> & VariantProps<typeof tabsContentVariants>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn(tabsContentVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Tabs, TabsContent, TabsList, TabsTrigger };

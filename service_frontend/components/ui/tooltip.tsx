'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { Tooltip as TooltipPrimitive } from 'radix-ui';

function TooltipProvider({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider data-slot="tooltip-provider" {...props} />;
}

// A bare Root (AC-DLA-16): the ONE provider lives in
// `providers/tooltips-provider.tsx`, mounted once for the whole app. A
// per-Tooltip provider would each carry its own 0ms `delayDuration` default
// and race the app-wide 700ms one.
function Tooltip({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

function TooltipTrigger({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

const tooltipVariants = cva(
  // Opacity only (AC-DLA-16) - no scale/slide keyframes, at --duration-fast.
  'z-(--z-modal) overflow-hidden rounded-md px-3 py-1.5 text-xs duration-(--duration-fast) animate-in fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
  {
    variants: {
      variant: {
        light: 'border border-border bg-background text-foreground shadow-md shadow-black/5',
        dark: 'dark:border dark:border-border bg-zinc-950 text-white dark:bg-zinc-300 dark:text-black shadow-md shadow-black/5',
      },
    },
    defaultVariants: {
      variant: 'dark',
    },
  },
);

function TooltipContent({
  className,
  sideOffset = 4,
  variant,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content> & VariantProps<typeof tooltipVariants>) {
  return (
    <TooltipPrimitive.Content
      data-slot="tooltip-content"
      sideOffset={sideOffset}
      className={cn(tooltipVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
